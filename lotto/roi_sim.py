"""Symulator polityk gry na danych historycznych.

Polityka: strategia, zakładów na losowanie, minimalna kumulacja (graj tylko powyżej),
miesięczny budżet, Lotto Plus. Dla każdej polityki:

- wynik zrealizowany: zakłady strategii (walk-forward) sprawdzone na prawdziwych losowaniach
  i prawdziwych wygranych, z pasem wyników przy H0 (silnik backtestu);
- ROI oczekiwane: suma EV zakładów przy faktycznych poziomach wygranych 3–5 w każdym
  losowaniu i odtworzonej kumulacji. Ma znacznie mniejszy szum niż wynik zrealizowany,
  który zależy od kilku rzadkich trafień.

Lotto Plus: brak danych o jego losowaniach, więc liczony tylko oczekiwanie (wygrana 1/14 mln).
"""
from __future__ import annotations

from datetime import date

import numpy as np

from lotto import config
from lotto.backtest import engine
from lotto.ev import PK, EVModel, net
from lotto.strategies import base as sb


def period_rows(ds: engine.Dataset, period: str) -> np.ndarray:
    """Losowania z danymi o wygranych i kumulacji w okresie (test: od split.test_since; all: wszystkie)."""
    ok = np.isfinite(ds.prize_table[:, 3:]).all(1) & np.isfinite(ds.jackpot if ds.jackpot is not None else np.nan)
    idx = np.flatnonzero(ok)
    if period == "test":
        cut = np.datetime64(date.fromisoformat(config.load()["split"]["test_since"]), "D")
        idx = idx[ds.d.dates[idx] >= cut]
    elif period != "all":
        raise ValueError("okres: test albo all")
    return idx


def choose_draws(ds: engine.Dataset, idx: np.ndarray, tickets: int, min_jackpot: float,
                 monthly_budget: float | None, lotto_plus: bool) -> np.ndarray:
    played, spent, month = [], 0.0, None
    plus = config.load()["lotto_plus"]["price"] if lotto_plus else 0.0
    for i in idx:
        if ds.jackpot[i] < min_jackpot:
            continue
        m = str(ds.d.dates[i])[:7]
        if m != month:
            month, spent = m, 0.0
        cost = tickets * (ds.price[i] + plus)
        if monthly_budget is not None and spent + cost > monthly_budget:
            continue
        spent += cost
        played.append(i)
    return np.array(played, int)


def expected_value(ds: engine.Dataset, rows: np.ndarray, evm: EVModel, anti: bool) -> np.ndarray:
    """EV jednego zakładu w każdym z losowań `rows` (przy faktycznych poziomach wygranych)."""
    m4 = evm.mult4_anti if anti else 1.0
    m5 = evm.mult5_anti if anti else 1.0
    pt = ds.prize_table[rows]
    out = PK[3] * pt[:, 3] + PK[4] * pt[:, 4] * m4 + PK[5] * pt[:, 5] * m5
    for j, i in enumerate(rows):
        J = float(ds.jackpot[i])
        lam = evm.sales(J) * PK[6] / m5
        share = (1 - np.exp(-lam)) / lam
        out[j] += PK[6] * net(J * share)
    return out


def simulate(ds: engine.Dataset, evm: EVModel, strategy: str = "random", params: dict | None = None,
             tickets: int = 1, min_jackpot: float = 0, monthly_budget: float | None = None,
             lotto_plus: bool = False, period: str = "test", sims: int = 300, seed: int = 1,
             realized: bool = True, progress=None) -> dict:
    idx = period_rows(ds, period)
    played = choose_draws(ds, idx, tickets, min_jackpot, monthly_budget, lotto_plus)
    plus_price = config.load()["lotto_plus"]["price"] if lotto_plus else 0.0
    years = max((ds.d.dates[idx[-1]] - ds.d.dates[idx[0]]).astype(int) / 365.25, 1e-9) if len(idx) else 1
    base = {"policy": {"strategy": strategy, "params": params or {}, "tickets": tickets, "min_jackpot": min_jackpot,
                       "monthly_budget": monthly_budget, "lotto_plus": lotto_plus, "period": period},
            "draws_available": int(len(idx)), "draws_played": int(len(played)),
            "range": [str(ds.d.dates[idx[0]]), str(ds.d.dates[idx[-1]])] if len(idx) else None,
            "years": float(years)}
    if not len(played):
        return base | {"cost": 0.0, "expected": None, "realized": None}

    anti = strategy == "anti_popular"
    ev_ticket = expected_value(ds, played, evm, anti)
    cost_main = float((ds.price[played] * tickets).sum())
    cost_plus = len(played) * tickets * plus_price
    cost = cost_main + cost_plus
    exp_win = float(ev_ticket.sum() * tickets + cost_plus * evm.lotto_plus()["ev"] / max(plus_price, 1e-9) * (plus_price > 0))
    out = base | {
        "cost": cost, "cost_per_year": cost / years,
        "expected": {"winnings": exp_win, "net": exp_win - cost, "roi": exp_win / cost - 1,
                     "net_per_year": (exp_win - cost) / years},
    }
    if realized:
        st = sb.get(strategy, **(params or {}))
        rng = np.random.default_rng(seed)
        tk = engine.walk_forward(ds, st, played, tickets, rng, progress)
        r = engine.evaluate(ds, played, tk, sims, seed, progress)
        m = r["money"]
        curve = np.array(r["curve"]["net"])
        win = m["winnings"]
        out["realized"] = {
            "winnings": win, "net": win - cost, "roi": win / cost - 1 if cost else None,
            "roi_h0_median": m["roi_h0_median"], "roi_h0_ci": m["roi_h0_ci"], "p_roi": m["p_roi"],
            "max_drawdown": float((np.maximum.accumulate(np.r_[0, curve]) - np.r_[0, curve]).max()),
            "tiers": r["tiers"], "best_draws": r["best_draws"],
            "curve": r["curve"] | {"net": (curve - np.linspace(0, cost_plus, len(curve))).round(2).tolist()},
            "lotto_plus_note": "Lotto Plus: koszt wliczony, wygrane tylko w ROI oczekiwanym (brak danych o losowaniach)."
            if lotto_plus else None,
        }
    return out


def policy_grid(ds: engine.Dataset, evm: EVModel, period: str = "test", tickets: int = 1) -> list[dict]:
    """ROI oczekiwane dla progów kumulacji × strategii (bez walk-forward, szybkie)."""
    rows = []
    for anti in (False, True):
        for thr in (0, 5e6, 10e6, 15e6, 20e6, 30e6, 40e6):
            r = simulate(ds, evm, "anti_popular" if anti else "random", None, tickets, thr, None, False,
                         period, realized=False)
            rows.append({"strategy": "anti_popular" if anti else "random", "min_jackpot": thr,
                         "draws_played": r["draws_played"], "draws_available": r["draws_available"],
                         "cost_per_year": r.get("cost_per_year"),
                         "roi": r["expected"]["roi"] if r["expected"] else None,
                         "net_per_year": r["expected"]["net_per_year"] if r["expected"] else None})
    return rows
