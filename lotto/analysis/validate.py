"""Walidacja detektorów na danych symulowanych.

1. Fałszywe alarmy: na danych zgodnych z H0 protokół nie może „potwierdzać” anomalii
   częściej niż w α przypadków, a wartości p muszą mieć rozkład jednostajny
   (odsetek p ≤ 0,05 ≈ 5%).
2. Kontrola pozytywna: dane z wstrzykniętą anomalią (obciążona kula, skłonność do
   powtarzania liczb z poprzedniego losowania) muszą być wykrywane, a skuteczność
   ma rosnąć z wielkością efektu.

Symulacje zachowują daty, liczbę losowań i dostępność kolejności kul z prawdziwych danych.

Użycie:
    python -m lotto.analysis.validate [--reps 20] [--sims 100]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime

import numpy as np

from lotto import config
from lotto.analysis import protocol
from lotto.analysis.data import K, N, DrawData, from_draws, simulate_like


def with_X(d: DrawData, X: np.ndarray, order: np.ndarray | None = None) -> DrawData:
    if order is None:
        order = np.full((len(X), K), -1, np.int16)
    order = order.copy()
    order[~d.has_order] = -1
    return DrawData(d.draw_no, d.dates, X, order)


def biased(d: DrawData, rng: np.random.Generator, number: int, weight: float) -> DrawData:
    w = np.ones(N)
    w[number - 1] = weight
    return simulate_like(d, rng, w)


def repeating(d: DrawData, rng: np.random.Generator, q: float) -> DrawData:
    """Z prawdopodobieństwem q jedna z liczb losowania t jest kopiowana z losowania t-1."""
    sim = simulate_like(d, rng)
    X = sim.X.copy()
    for t in range(1, len(X)):
        if rng.random() < q:
            prev = np.flatnonzero(X[t - 1] & ~X[t])
            if len(prev):
                cur = np.flatnonzero(X[t] & ~X[t - 1])
                X[t, rng.choice(cur)] = False
                X[t, rng.choice(prev)] = True
    return with_X(d, X)


def _protocol(d: DrawData, test_since: date, sims: int, alpha: float, seed: int) -> dict:
    return protocol.run(d, test_since, sims, 0, alpha, seed)


def false_alarms(d: DrawData, test_since: date, reps: int, sims: int, alpha: float, seed: int,
                 progress=None) -> dict:
    rng = np.random.default_rng(seed)
    any_confirmed, p_le, total = 0, 0, 0
    confirmed_ids: dict[str, int] = {}
    for i in range(reps):
        r = _protocol(simulate_like(d, rng), test_since, sims, alpha, seed + 1000 + i)
        hyps = [h for h in r["hypotheses"] if h["train"]]
        p_le += sum(h["train"]["p"] <= 0.05 for h in hyps)
        total += len(hyps)
        conf = [h["id"] for h in r["hypotheses"] if h["verdict"] == "confirmed" and h["train"]]
        any_confirmed += bool(conf)
        for c in conf:
            confirmed_ids[c] = confirmed_ids.get(c, 0) + 1
        if progress:
            progress("Fałszywe alarmy", i + 1, reps)
    return {"reps": reps, "rate_any_confirmed": any_confirmed / reps,
            "share_p_le_005": p_le / total, "confirmed_ids": confirmed_ids}


def positive_control(d: DrawData, test_since: date, reps: int, sims: int, alpha: float, seed: int,
                     progress=None) -> list[dict]:
    rng = np.random.default_rng(seed)
    scenarios = [
        ("Kula 7: waga 1,15", "freq.07", lambda: biased(d, rng, 7, 1.15)),
        ("Kula 7: waga 1,30", "freq.07", lambda: biased(d, rng, 7, 1.30)),
        ("Kula 7: waga 1,50", "freq.07", lambda: biased(d, rng, 7, 1.50)),
        ("Powtórka liczby z poprzedniego losowania w 10% losowań", "lag.01", lambda: repeating(d, rng, 0.10)),
        ("Powtórka liczby z poprzedniego losowania w 25% losowań", "lag.01", lambda: repeating(d, rng, 0.25)),
    ]
    out = []
    step, total = 0, reps * len(scenarios)
    for name, target, make in scenarios:
        hit_target, hit_any, rel = 0, 0, []
        for i in range(reps):
            sim = make()
            if target.startswith("freq"):
                rel.append(sim.X[:, int(target[-2:]) - 1].mean() / (K / N) - 1)
            r = _protocol(sim, test_since, sims, alpha, seed + 5000 + step)
            ver = {h["id"]: h["verdict"] for h in r["hypotheses"]}
            hit_target += ver.get(target) == "confirmed"
            hit_any += any(v == "confirmed" for v in ver.values())
            step += 1
            if progress:
                progress("Kontrola pozytywna", step, total)
        out.append({"scenario": name, "target": target, "reps": reps,
                    "detected_target": hit_target / reps, "detected_any": hit_any / reps,
                    "effect": float(np.mean(rel)) if rel else None})
    return out


def run_from_db(reps: int = 20, sims: int = 100, seed: int = 7, progress=None) -> dict:
    from lotto.data import db
    cfg = config.load()
    conn = db.connect()
    try:
        d = from_draws(db.load_draws(conn, since=date.fromisoformat(cfg["data"]["analysis_since"])))
    finally:
        conn.close()
    test_since = date.fromisoformat(cfg["split"]["test_since"])
    alpha = cfg["analysis"]["alpha"]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params": {"reps": reps, "sims": sims, "seed": seed, "alpha": alpha},
        "false_alarms": false_alarms(d, test_since, reps, sims, alpha, seed, progress),
        "positive_control": positive_control(d, test_since, max(reps // 2, 5), sims, alpha, seed, progress),
    }
    path = config.ROOT / "data" / "validation_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def load_report() -> dict | None:
    path = config.ROOT / "data" / "validation_report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    r = run_from_db(args.reps, args.sims, args.seed,
                    lambda ph, i, n: print(f"  {ph}: {i}/{n}", flush=True))
    fa = r["false_alarms"]
    print(f"\nFałszywe alarmy: {fa['rate_any_confirmed']:.0%} powtórzeń z „potwierdzoną” anomalią "
          f"(cel ≤ {r['params']['alpha']:.0%}); odsetek p ≤ 0,05: {fa['share_p_le_005']:.1%} (cel ≈ 5%)")
    if fa["confirmed_ids"]:
        print(f"  fałszywie potwierdzone: {fa['confirmed_ids']}")
    print("Kontrola pozytywna:")
    for s in r["positive_control"]:
        eff = f" (efekt {s['effect']:+.1%})" if s["effect"] is not None else ""
        print(f"  {s['scenario']}{eff}: wykryto {s['detected_target']:.0%} (jakąkolwiek anomalię: {s['detected_any']:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
