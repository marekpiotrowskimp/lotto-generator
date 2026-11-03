"""Backtest walk-forward strategii z porównaniem do losowości.

Przed każdym losowaniem okresu strategia dostaje wyłącznie wcześniejsze losowania
(widoki tylko do odczytu) i zwraca T zakładów. Liczymy trafienia, wygrane i ROI.

Punkt odniesienia (H0): TE SAME zakłady sprawdzone na losowaniach symulowanych
(6 z 49, jednostajnie). Przy H0 prawdziwe losowania są niezależne od zakładów
(strategia nie zna przyszłości), więc rozkład wyniku na symulacjach to dokładnie
rozkład wyniku „przez przypadek”. Wartość p = jak często przypadek daje wynik
co najmniej tak dobry jak strategia.

Użycie:
    python -m lotto.backtest.engine --strategy hot --tickets 5 --period test
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from scipy import stats

from lotto import config
from lotto.analysis.data import K, N, DrawData, from_draws, simulate
from lotto.strategies import base as strategies

WARMUP = 200   # na train pomijamy pierwsze losowania (strategie potrzebują historii)
HIT_PMF = stats.hypergeom(N, K, K).pmf(np.arange(K + 1))


@dataclass
class Dataset:
    d: DrawData
    prize_table: np.ndarray    # (n, 7): wartość netto wygranej za k trafień w losowaniu; NaN = brak danych
    price: np.ndarray          # (n,) cena zakładu
    estimated6: np.ndarray     # (n,) bool: wygrana za 6 oszacowana (brak zwycięzcy w danych)
    jackpot: np.ndarray | None = None   # (n,) kumulacja brutto w losowaniu (odtworzona), NaN = brak


def _net(v: float, tax: dict) -> float:
    return v * (1 - tax["rate"]) if v > tax["threshold"] else v


def build_prize_table(d: DrawData, prizes: dict[int, dict[int, tuple[int, float]]],
                      jackpots: dict[int, float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Wygrana netto za 3–6 trafień w każdym losowaniu, gdybyśmy grali.

    - 3: kwota z danych (stała), awaryjnie z config.yaml;
    - 4, 5: kwota z danych; dołączając do zwycięzców dzielimy pulę: a·w/(w+1);
    - 6: jak wyżej, a gdy nikt nie trafił (kwota 0 w danych): odtworzona kumulacja
      (`jackpots`, lotto/analysis/jackpot.py), awaryjnie gwarantowana pula z config.yaml;
    - podatek 10% od wygranej powyżej progu.
    """
    cfg = config.load()
    tax = cfg["tax"]
    table = np.full((len(d), K + 1), np.nan)
    est6 = np.zeros(len(d), bool)
    for i, (no, dt64) in enumerate(zip(d.draw_no, d.dates)):
        pz = prizes.get(int(no))
        if not pz:
            continue
        day = dt64.astype(object)
        row = np.zeros(K + 1)
        for k in (3, 4, 5, 6):
            w, a = pz.get(k, (0, 0.0))
            if k == 3:
                v = a or (config.fixed_prizes(day) or {}).get("prize_3", 0)
            elif w > 0:
                v = a * w / (w + 1)
            elif k == 6:
                jv = (jackpots or {}).get(int(no))
                v = jv if jv and np.isfinite(jv) else (config.fixed_prizes(day) or {}).get("min_jackpot", 0)
                est6[i] = True
            else:
                v = np.nan
            row[k] = _net(v, tax) if np.isfinite(v) else np.nan
        table[i] = row
    return table, est6


def load_dataset() -> Dataset:
    from lotto.data import db
    cfg = config.load()
    conn = db.connect()
    try:
        d = from_draws(db.load_draws(conn, since=date.fromisoformat(cfg["data"]["analysis_since"])))
        prizes: dict[int, dict[int, tuple[int, float]]] = {}
        for r in conn.execute("SELECT draw_no, tier, winners, amount FROM prizes"):
            prizes.setdefault(r["draw_no"], {})[r["tier"]] = (r["winners"], r["amount"])
    finally:
        conn.close()
    from lotto.analysis import jackpot as jp
    from lotto.data import db as _db
    conn = _db.connect()
    try:
        st = _db.get_state(conn, "next_jackpot")
    finally:
        conn.close()
    js = jp.reconstruct(d, prizes, float(st["value"]) if st else None)
    jackpots = {int(d.draw_no[r]): float(j) for r, j in zip(js.rows, js.jackpot)}
    table, est6 = build_prize_table(d, prizes, jackpots)
    price = np.array([config.ticket_price(x.astype(object)) or np.nan for x in d.dates])
    jackpot = np.full(len(d), np.nan)
    jackpot[js.rows] = js.jackpot
    return Dataset(d, table, price, est6, jackpot)


def period_indices(d: DrawData, period: str, test_since: date) -> np.ndarray:
    cut = np.datetime64(test_since, "D")
    idx = np.arange(len(d))
    if period == "test":
        return idx[d.dates >= cut]
    if period == "train":
        return idx[(d.dates < cut) & (idx >= WARMUP)]
    raise ValueError("okres: train albo test")


def walk_forward(ds: Dataset, strategy: strategies.Strategy, idx: np.ndarray, n_tickets: int,
                 rng: np.random.Generator, progress=None) -> np.ndarray:
    """Zakłady (D, T, 6) dla każdego losowania z `idx`, z historii sprzed niego."""
    out = np.empty((len(idx), n_tickets, K), np.int16)
    for j, t in enumerate(idx):
        tk = np.asarray(strategy.generate(ds.d.head(int(t)), n_tickets, rng))
        if tk.shape != (n_tickets, K):
            raise ValueError(f"{strategy.name}: zły kształt zakładów {tk.shape}")
        srt = np.sort(tk, axis=1)
        if (srt < 1).any() or (srt > N).any() or (np.diff(srt, axis=1) == 0).any():
            raise ValueError(f"{strategy.name}: niepoprawny zakład w losowaniu {ds.d.draw_no[t]}: {tk}")
        out[j] = srt
        if progress and (j + 1) % 50 == 0:
            progress("Strategia typuje", j + 1, len(idx))
    return out


def _onehot(tickets: np.ndarray) -> np.ndarray:
    D, T, _ = tickets.shape
    oh = np.zeros((D, T, N), np.int8)
    np.put_along_axis(oh, tickets.astype(np.int64) - 1, 1, axis=2)
    return oh


def evaluate(ds: Dataset, idx: np.ndarray, tickets: np.ndarray, sims: int, seed: int, progress=None) -> dict:
    D, T, _ = tickets.shape
    oh = _onehot(tickets)
    Xd = ds.d.X[idx].astype(np.int8)
    hits = np.einsum("dtn,dn->dt", oh, Xd, dtype=np.int32)
    prize = ds.prize_table[idx]                      # (D, 7)
    covered = np.isfinite(prize[:, 3:]).all(1)       # losowania z pełnymi danymi o wygranych
    prize0 = np.nan_to_num(prize)
    price = ds.price[idx]

    def money(h):  # h: (D, T) trafienia → wygrane na losowanie (tylko pokryte)
        return np.take_along_axis(prize0, h, axis=1).sum(1) * covered

    win_draw = money(hits)
    cost_draw = T * price * covered
    counts = {k: int((hits == k).sum()) for k in range(K + 1)}

    # baseline: te same zakłady, losowania symulowane
    rng = np.random.default_rng(seed + 99991)
    sim_mean, sim_ge3, sim_win = np.empty(sims), np.empty(sims), np.empty(sims)
    sim_counts = np.empty((sims, K + 1))
    sim_curves = np.empty((sims, D), np.float32)
    for s in range(sims):
        Xs, _ = simulate(D, rng)
        h = np.einsum("dtn,dn->dt", oh, Xs.astype(np.int8), dtype=np.int32)
        sim_mean[s] = h.mean()
        sim_ge3[s] = (h >= 3).sum()
        sim_counts[s] = np.bincount(h.ravel(), minlength=K + 1)[: K + 1]
        w = money(h)
        sim_win[s] = w.sum()
        sim_curves[s] = np.cumsum(w - cost_draw)
        if progress and (s + 1) % 50 == 0:
            progress("Symulacje H0", s + 1, sims)

    obs_mean, obs_ge3 = float(hits.mean()), int((hits >= 3).sum())
    cost = float(cost_draw.sum())
    win = float(win_draw.sum())
    q = lambda a, p: float(np.quantile(a, p))  # noqa: E731
    tiers = []
    for k in range(3, K + 1):
        tiers.append({
            "hits": k, "observed": counts[k], "expected": float(D * T * HIT_PMF[k]),
            "ci": [q(sim_counts[:, k], 0.025), q(sim_counts[:, k], 0.975)],
        })
    step = max(1, D // 300)   # krzywe salda: najwyżej ~300 punktów
    pts = np.arange(0, D, step)
    if pts[-1] != D - 1:
        pts = np.append(pts, D - 1)
    curve = np.cumsum(win_draw - cost_draw)
    return {
        "draws": D, "tickets_per_draw": T, "tickets": D * T,
        "mean_hits": obs_mean, "mean_hits_h0": K * K / N,
        "mean_hits_ci": [q(sim_mean, 0.025), q(sim_mean, 0.975)],
        "p_mean_hits": float((1 + (sim_mean >= obs_mean).sum()) / (1 + sims)),
        "wins_ge3": obs_ge3, "wins_ge3_ci": [q(sim_ge3, 0.025), q(sim_ge3, 0.975)],
        "p_wins_ge3": float((1 + (sim_ge3 >= obs_ge3).sum()) / (1 + sims)),
        "tiers": tiers,
        "money": {
            "covered_draws": int(covered.sum()), "cost": cost, "winnings": win, "net": win - cost,
            "roi": (win - cost) / cost if cost else None,
            "roi_h0_mean": float(((sim_win - cost) / cost).mean()) if cost else None,
            "roi_h0_median": float(np.median((sim_win - cost) / cost)) if cost else None,
            "roi_h0_ci": [q((sim_win - cost) / cost, 0.025), q((sim_win - cost) / cost, 0.975)] if cost else None,
            "p_roi": float((1 + (sim_win >= win).sum()) / (1 + sims)) if cost else None,
            "estimated_jackpots": int((ds.estimated6[idx] & (hits == 6).any(1)).sum()),
        },
        "curve": {
            "dates": [str(ds.d.dates[idx[i]]) for i in pts],
            "net": curve[pts].round(2).tolist(),
            "h0_median": np.median(sim_curves[:, pts], axis=0).round(2).tolist(),
            "h0_lo": np.quantile(sim_curves[:, pts], 0.05, axis=0).round(2).tolist(),
            "h0_hi": np.quantile(sim_curves[:, pts], 0.95, axis=0).round(2).tolist(),
        },
        "best_draws": [
            {"draw_no": int(ds.d.draw_no[idx[i]]), "date": str(ds.d.dates[idx[i]]), "hits": int(hits[i].max()),
             "ticket": tickets[i, int(hits[i].argmax())].tolist(), "numbers": ds.d.numbers[idx[i]].tolist(),
             "won": float(win_draw[i])}
            for i in np.argsort(-hits.max(1) * 1e7 - win_draw)[:5] if hits[i].max() >= 3
        ],
    }


def run(ds: Dataset, strategy_name: str, params: dict | None = None, n_tickets: int = 1,
        period: str = "test", sims: int = 500, seed: int = 1, progress=None) -> dict:
    t0 = time.time()
    cfg = config.load()
    strategy = strategies.get(strategy_name, **(params or {}))
    idx = period_indices(ds.d, period, date.fromisoformat(cfg["split"]["test_since"]))
    rng = np.random.default_rng(seed)
    tickets = walk_forward(ds, strategy, idx, n_tickets, rng, progress)
    res = evaluate(ds, idx, tickets, sims, seed, progress)
    alpha = cfg["analysis"]["alpha"]
    res.update({
        "strategy": strategy.describe() | {"values": strategy.p},
        "period": period, "range": [str(ds.d.dates[idx[0]]), str(ds.d.dates[idx[-1]])],
        "sims": sims, "seed": seed, "alpha": alpha,
        "beats_random": res["p_mean_hits"] <= alpha,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_s": round(time.time() - t0, 1),
    })
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", default="random", choices=sorted(strategies.REGISTRY))
    ap.add_argument("--param", action="append", default=[], help="parametr strategii, np. window=50")
    ap.add_argument("--tickets", type=int, default=1)
    ap.add_argument("--period", default="test", choices=["train", "test"])
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    params = dict(kv.split("=", 1) for kv in args.param)
    r = run(load_dataset(), args.strategy, params, args.tickets, args.period, args.sims, args.seed)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    m = r["money"]
    print(f"{r['strategy']['label']} {r['strategy']['values']} · {r['period']} {r['range']} · "
          f"{r['draws']} losowań × {r['tickets_per_draw']} zakł.")
    print(f"Średnio trafień: {r['mean_hits']:.4f} (H0 {r['mean_hits_h0']:.4f}, 95%: "
          f"{r['mean_hits_ci'][0]:.4f}–{r['mean_hits_ci'][1]:.4f}), p = {r['p_mean_hits']:.3f}")
    for t in r["tiers"]:
        print(f"  {t['hits']} trafienia: {t['observed']} (oczekiwane {t['expected']:.1f}, 95%: {t['ci'][0]:.0f}–{t['ci'][1]:.0f})")
    if m["roi"] is not None:
        print(f"Koszt {m['cost']:,.0f} zł, wygrane {m['winnings']:,.0f} zł, ROI {m['roi']:+.1%} "
              f"(H0: mediana {m['roi_h0_median']:+.1%}, średnia {m['roi_h0_mean']:+.1%}, "
              f"95%: {m['roi_h0_ci'][0]:+.1%}…{m['roi_h0_ci'][1]:+.1%}); "
              f"losowań z danymi o wygranych: {m['covered_draws']}")
    print("Lepsza od losowości: " + ("TAK" if r["beats_random"] else "nie") + f" ({r['runtime_s']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
