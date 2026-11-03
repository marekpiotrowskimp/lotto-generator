"""Protokół badania H0: wykrycie na train → potwierdzenie na test.

1. Wszystkie detektory na train; korekta Benjaminiego–Hochberga na całą rodzinę hipotez.
2. Hipotezy istotne na train (q ≤ α) są „zamrażane” i sprawdzane na test
   z korektą Bonferroniego na liczbę wybranych hipotez.
3. Anomalia jest POTWIERDZONA tylko wtedy, gdy przejdzie oba kroki.
4. Test modelem (5.5) jest z natury train → test; potwierdzony, gdy p_perm ≤ α.

Wynik na pełnych danych jest pokazywany informacyjnie, nie służy do werdyktu.

Użycie:
    python -m lotto.analysis.protocol [--sims 1000] [--perms 200] [--seed 1]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from typing import Callable

import numpy as np
from scipy import stats

from lotto import config
from lotto.analysis import detectors as dt
from lotto.analysis import ml
from lotto.analysis.data import K, N, P, DrawData, from_draws, simulate_like, split

Progress = Callable[[str, int, int], None]


def bh(p: np.ndarray) -> np.ndarray:
    """Wartości q Benjaminiego–Hochberga."""
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    q = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(q, 1)
    return out


def run_detectors(d: DrawData, rng: np.random.Generator, sims: int,
                  progress: Progress | None = None, label: str = "") -> list[dt.Result]:
    results = [r for f in dt.ANALYTIC for r in f(d)]
    obs = dt.mc_statistics(d)
    exceed = dict.fromkeys(obs, 0)
    for s in range(sims):
        null = dt.mc_statistics(simulate_like(d, rng))
        for k in obs:
            exceed[k] += null[k] >= obs[k]
        if progress and (s + 1) % 25 == 0:
            progress(f"Monte Carlo ({label})", s + 1, sims)
    for k, (group, name) in dt.MONTE_CARLO.items():
        results.append(dt.Result(f"mc.{k}", group, name, f"Monte Carlo ({sims} symulacji)",
                                 obs[k], (1 + exceed[k]) / (1 + sims), None, "", len(d)))
    return results


def power_table(n_train: int, n_test: int, m_train: int, alpha: float) -> list[dict]:
    """Najmniejsze efekty, które protokół wykrywa z mocą 80% (wykrycie na train × potwierdzenie na test).

    Na train zakładamy próg Bonferroniego na całą rodzinę (ostrożnie; BH jest łagodniejszy),
    na test próg α (jedna wybrana hipoteza).
    """
    zt = stats.norm.isf(alpha / (2 * m_train))
    zs = stats.norm.isf(alpha / 2)

    def detect(delta_se_train, delta_se_test):
        pw = lambda z, crit: stats.norm.sf(crit - z) + stats.norm.cdf(-crit - z)  # noqa: E731
        return pw(delta_se_train, zt) * pw(delta_se_test, zs)

    def minimal(se_rel: Callable[[int], float]) -> float:
        lo, hi = 0.0, 5.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if detect(mid / se_rel(n_train), mid / se_rel(n_test)) >= 0.8:
                hi = mid
            else:
                lo = mid
        return hi

    hyp_sd = np.sqrt(dt.HYPER_VAR) / dt.HYPER_MEAN
    g = 9  # najmniejsza grupa fizyczna z 5.1 (kule jednocyfrowe)
    g_sd = np.sqrt(K * (g / N) * (1 - g / N) * ((N - K) / (N - 1))) / (K * g / N)
    rows = [
        ("Obciążenie jednej liczby (częstość)", lambda n: np.sqrt((1 - P) / (n * P)),
         "względna zmiana częstości liczby"),
        ("Obciążenie grupy kul jednocyfrowych", lambda n: g_sd / np.sqrt(n),
         "względna zmiana częstości grupy"),
        ("Powtarzanie liczb z poprzedniego losowania", lambda n: hyp_sd / np.sqrt(n),
         "względna zmiana średniej liczby powtórzeń"),
    ]
    out = []
    for name, se, unit in rows:
        eff = minimal(se)
        out.append({"test": name, "min_effect": eff, "unit": unit,
                    "example": f"{eff * 100:.1f}%",
                    "single_stage_full": float((stats.norm.isf(alpha / 2) + stats.norm.isf(0.2))
                                               * se(n_train + n_test))})
    return out


def chart_data(d: DrawData) -> dict:
    n = len(d)
    c = d.X.sum(0)
    gaps = np.concatenate([np.diff(np.flatnonzero(d.X[:, i])) for i in range(N)])
    gmax = 40
    g_obs = np.bincount(np.minimum(gaps, gmax), minlength=gmax + 1)[1:]
    k = np.arange(1, gmax + 1)
    g_exp = len(gaps) * (1 - P) ** (k - 1) * P
    g_exp[-1] = len(gaps) * (1 - P) ** (gmax - 1)
    o = dt.overlaps(d, 1)
    pmf = stats.hypergeom(N, K, K).pmf(np.arange(K + 1))
    lags = []
    for lag in range(1, 21):
        ol = dt.overlaps(d, lag)
        lags.append({"lag": lag, "mean": float(ol.mean()),
                     "ci": float(1.96 * np.sqrt(dt.HYPER_VAR / len(ol)))})
    order = d.order[d.has_order]
    years = d.dates.astype("datetime64[Y]").astype(int) + 1970
    return {
        "frequency": {"counts": c.tolist(), "expected": n * P, "sd": float(np.sqrt(n * P * (1 - P)))},
        "gaps": {"observed": g_obs.tolist(), "expected": g_exp.tolist(), "last_bin_is_tail": True},
        "repeats": {"observed": np.bincount(o, minlength=K + 1).tolist(), "expected": (len(o) * pmf).tolist()},
        "lags": {"rows": lags, "h0": dt.HYPER_MEAN},
        "positions": {"means": [float(order[:, k].mean()) for k in range(K)] if len(order) else [],
                      "ci": float(1.96 * np.sqrt((N * N - 1) / 12 / max(len(order), 1))), "h0": 25.0,
                      "n": int(len(order))},
        "years": {"from": int(years.min()), "to": int(years.max())},
    }


def run(d_all: DrawData, test_since: date, sims: int, perms: int, alpha: float, seed: int = 1,
        progress: Progress | None = None) -> dict:
    t0 = time.time()
    rng = np.random.default_rng(seed)
    train, test = split(d_all, test_since)
    r_train = run_detectors(train, rng, sims, progress, "train")
    r_test = {r.id: r for r in run_detectors(test, rng, sims, progress, "test")}
    r_full = {r.id: r for r in run_detectors(d_all, rng, 0)}   # informacyjnie, bez Monte Carlo

    q = bh([r.p for r in r_train])
    selected = [r.id for r, qq in zip(r_train, q) if qq <= alpha]
    k_sel = max(len(selected), 1)

    hyps = []
    for r, qq in zip(r_train, q):
        te = r_test.get(r.id)
        sel = r.id in selected
        confirmed = bool(sel and te is not None and te.p <= alpha / k_sel)
        hyps.append({
            "id": r.id, "group": r.group, "name": r.name, "method": r.method,
            "effect_label": r.effect_label,
            "train": {"stat": r.stat, "p": r.p, "q": float(qq), "effect": r.effect, "n": r.n, **r.extra},
            "test": te.to_dict() if te else None,
            "full": {"p": r_full[r.id].p, "effect": r_full[r.id].effect} if r.id in r_full else None,
            "selected": sel,
            "verdict": "confirmed" if confirmed else ("train_only" if sel else "none"),
        })

    train_mask = d_all.dates < np.datetime64(test_since, "D")
    m = ml.predictability(d_all, train_mask, perms, rng,
                          (lambda i, n: progress("Test modelem (permutacje)", i, n)) if progress else None)
    ml_confirmed = perms > 0 and m.p <= alpha
    hyps.append({
        "id": m.id, "group": m.group, "name": m.name, "method": m.method, "effect_label": m.effect_label,
        "train": None, "test": m.to_dict(), "full": None, "selected": True,
        "verdict": "confirmed" if ml_confirmed else "none",
    })

    confirmed = [h for h in hyps if h["verdict"] == "confirmed"]
    groups = {}
    for h in hyps:
        g = groups.setdefault(h["group"], {"tests": 0, "selected": 0, "confirmed": 0, "min_p_train": 1.0})
        g["tests"] += 1
        g["selected"] += h["selected"] and h["train"] is not None
        g["confirmed"] += h["verdict"] == "confirmed"
        if h["train"]:
            g["min_p_train"] = min(g["min_p_train"], h["train"]["p"])

    def rng_of(x: DrawData) -> list[str]:
        return [str(x.dates[0]), str(x.dates[-1])]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_s": round(time.time() - t0, 1),
        "params": {"alpha": alpha, "sims": sims, "perms": perms, "seed": seed, "test_since": str(test_since)},
        "data": {"n_all": len(d_all), "n_train": len(train), "n_test": len(test),
                 "train_range": rng_of(train), "test_range": rng_of(test),
                 "n_order_train": int(train.has_order.sum()), "n_order_test": int(test.has_order.sum())},
        "summary": {
            "n_hypotheses": len(hyps), "n_selected_train": len(selected), "n_confirmed": len(confirmed),
            "h0_rejected": bool(confirmed),
            "expected_false_train_p05": round(0.05 * len(r_train), 1),
            "n_train_p05": int(sum(r.p <= 0.05 for r in r_train)),
            "groups": groups,
        },
        "hypotheses": hyps,
        "power": power_table(len(train), len(test), len(r_train), alpha),
        "charts": chart_data(d_all),
    }


def run_from_db(progress: Progress | None = None, sims: int | None = None, perms: int | None = None,
                seed: int = 1) -> dict:
    from lotto.data import db
    cfg = config.load()
    a = cfg["analysis"]
    conn = db.connect()
    try:
        d = from_draws(db.load_draws(conn, since=date.fromisoformat(cfg["data"]["analysis_since"])))
        last = db.last_draw(conn)
    finally:
        conn.close()
    report = run(d, date.fromisoformat(cfg["split"]["test_since"]),
                 a["mc_sims"] if sims is None else sims, a["ml_permutations"] if perms is None else perms,
                 a["alpha"], seed, progress)
    report["data"]["last_draw_no"] = last["draw_no"] if last else None
    path = config.ROOT / a["report_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def load_report() -> dict | None:
    path = config.ROOT / config.load()["analysis"]["report_path"]
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sims", type=int)
    ap.add_argument("--perms", type=int)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    last = [None]

    def progress(phase, i, n):
        if (phase, i * 10 // n) != last[0]:
            last[0] = (phase, i * 10 // n)
            print(f"  {phase}: {i}/{n}", flush=True)

    r = run_from_db(progress, args.sims, args.perms, args.seed)
    s, dd = r["summary"], r["data"]
    print(f"\nTrain: {dd['n_train']} losowań {dd['train_range']}, test: {dd['n_test']} {dd['test_range']}")
    print(f"Hipotez: {s['n_hypotheses']}; p ≤ 0,05 na train: {s['n_train_p05']} "
          f"(przy H0 oczekiwane ~{s['expected_false_train_p05']})")
    print(f"Istotne na train po korekcie BH: {s['n_selected_train']}; potwierdzone na test: {s['n_confirmed']}")
    for h in r["hypotheses"]:
        if h["selected"] and h["train"]:
            print(f"  {h['id']}: q_train={h['train']['q']:.3g}, p_test={h['test']['p']:.3g} → {h['verdict']}")
    ml_h = r["hypotheses"][-1]
    print(f"Model: zysk {ml_h['test']['stat']:+.2f} (log-loss ×1e4), p_perm={ml_h['test']['p']:.3g}, "
          f"trafienia top-6 = {ml_h['test']['effect']:.3f} (H0 0,735)")
    print("\nWERDYKT: " + ("H0 ODRZUCONA – potwierdzone anomalie" if s["h0_rejected"]
                          else "brak podstaw do odrzucenia H0"))
    print("\nMoc (najmniejszy efekt wykrywany z prawdopodobieństwem 80%):")
    for p in r["power"]:
        print(f"  {p['test']}: {p['min_effect'] * 100:.1f}% ({p['unit']})")
    print(f"\nRaport: {config.load()['analysis']['report_path']} ({r['runtime_s']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
