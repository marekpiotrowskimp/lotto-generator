"""Odtworzenie kumulacji (puli na szóstkę) i sprzedaży dla losowań z danymi o wygranych.

Dane podają kwotę za szóstkę tylko wtedy, gdy ktoś ją trafił. Odtwarzamy pulę w każdym losowaniu:
- po losowaniu z szóstką pula wraca do gwarantowanego minimum (config: fixed_prizes.min_jackpot),
- w losowaniu z szóstką pula = liczba zwycięzców × wygrana,
- pomiędzy nimi pula rośnie proporcjonalnie do sprzedaży kolejnych losowań,
- ostatni, niezakończony łańcuch kończy się zapowiadaną kumulacją na najbliższe losowanie.

Sprzedaż (liczba zakładów) szacujemy z liczby zwycięzców z trójką: N ≈ W3 / P(3).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from lotto import config
from lotto.analysis.data import K, N, DrawData

P3 = stats.hypergeom(N, K, K).pmf(3)


@dataclass
class JackpotSeries:
    rows: np.ndarray        # indeksy w DrawData
    jackpot: np.ndarray     # pula na szóstkę w losowaniu (zł, brutto)
    sales: np.ndarray       # szacowana liczba zakładów
    winners6: np.ndarray
    exact: np.ndarray       # True: pula znana (ktoś wygrał), False: odtworzona
    next_jackpot: float | None   # pula na najbliższe losowanie (zapowiedź)


def reconstruct(d: DrawData, prizes: dict[int, dict[int, tuple[int, float]]],
                announced_next: float | None = None) -> JackpotSeries:
    rows = np.array([i for i, no in enumerate(d.draw_no) if all(k in prizes.get(int(no), {}) for k in (3, 6))], int)
    if len(rows) == 0:
        return JackpotSeries(rows, *(np.array([]) for _ in range(3)), np.array([], bool), announced_next)
    W3 = np.array([prizes[int(d.draw_no[i])][3][0] for i in rows], float)
    W6 = np.array([prizes[int(d.draw_no[i])][6][0] for i in rows], int)
    A6 = np.array([prizes[int(d.draw_no[i])][6][1] for i in rows], float)
    sales = W3 / P3
    jackpot = np.full(len(rows), np.nan)
    exact = W6 > 0
    jackpot[exact] = W6[exact] * A6[exact]

    def min_jp(i):
        fp = config.fixed_prizes(d.dates[rows[i]].astype(object)) or {}
        return float(fp.get("min_jackpot", 2_000_000))

    # łańcuchy: od losowania po wygranej do kolejnej wygranej (włącznie)
    wins = np.flatnonzero(exact)
    starts = [w + 1 for w in wins]
    for a in starts:
        if a >= len(rows):
            continue
        nxt = wins[wins >= a]
        if len(nxt):
            b, end_value, last = nxt[0], jackpot[nxt[0]], nxt[0]
        elif announced_next:
            b, end_value, last = len(rows), announced_next, len(rows) - 1
        else:
            continue
        j0 = min_jp(a)
        seg = np.arange(a, b)            # losowania bez wygranej przed końcem łańcucha
        if len(seg) == 0:
            continue
        w = sales[a:b] if b < len(rows) else sales[a:]
        cum = np.r_[0, np.cumsum(w)][:len(seg)]
        total = w.sum()
        jackpot[seg] = j0 + (max(end_value, j0) - j0) * cum / total
    # początek danych przed pierwszą wygraną: nieznany
    return JackpotSeries(rows, jackpot, sales, W6, exact, announced_next)


def sales_model(js: JackpotSeries) -> tuple[float, float]:
    """log(sprzedaż) = a + b·log(pula): sprzedaż rośnie z kumulacją."""
    ok = np.isfinite(js.jackpot)
    b, a = np.polyfit(np.log(js.jackpot[ok]), np.log(js.sales[ok]), 1)
    return float(a), float(b)
