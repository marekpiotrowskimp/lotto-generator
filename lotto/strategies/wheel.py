"""Pokrycie puli liczb (wheeling): zakłady z gwarancją trafień.

Gwarancja „t jeśli k” dla puli m liczb: jeśli co najmniej k wylosowanych liczb
jest w puli, to co najmniej jeden zakład ma ≥ t trafień.

- system pełny: wszystkie C(m, 6) zakładów (gwarancja 6 jeśli 6),
- system skrócony: zachłanne pokrycie wszystkich k-podzbiorów puli; zwykle dużo
  mniej zakładów niż system pełny. Gwarancję sprawdzamy wyczerpująco.

System nie zmienia szansy na zakład ani EV; zmienia rozkład wyników
(mniejsza wariancja przy trafieniu liczb z puli).
"""
from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np

from lotto.analysis.data import K

MAX_POOL = 18
GUARANTEES = {"3if3": (3, 3), "3if4": (3, 4), "3if5": (3, 5), "3if6": (3, 6), "4if4": (4, 4),
              "4if5": (4, 5), "4if6": (4, 6), "5if5": (5, 5), "5if6": (5, 6), "6if6": (6, 6)}


def _masks(items: list[tuple[int, ...]]) -> np.ndarray:
    m = np.zeros((len(items), MAX_POOL), bool)
    for i, it in enumerate(items):
        m[i, list(it)] = True
    return m


def cover(pool: list[int], t: int, k: int, rng: np.random.Generator | None = None, tries: int = 30) -> np.ndarray:
    """Zakłady (n, 6) z puli dających gwarancję „t jeśli k” (najmniejsze z `tries` zachłannych pokryć)."""
    pool = sorted(set(int(x) for x in pool))
    m = len(pool)
    if not K <= m <= MAX_POOL:
        raise ValueError(f"pula musi mieć od 6 do {MAX_POOL} liczb (ma {m})")
    if not 1 <= t <= k <= K:
        raise ValueError("gwarancja: 1 ≤ t ≤ k ≤ 6")
    if (t, k) == (6, 6) or m == K:
        tickets = list(combinations(range(m), K))
    else:
        rng = rng or np.random.default_rng(0)
        cands = list(combinations(range(m), K))
        targets = list(combinations(range(m), k))
        C = _masks(cands).astype(np.int8)
        S = _masks(targets).astype(np.int8)
        covers = (C @ S.T) >= t                       # (kandydaci, k-podzbiory)
        tickets = None
        tries = max(2, min(tries, 30_000 // len(cands)))   # duże pule: mniej prób (czas)
        for _ in range(tries):
            uncovered = np.ones(len(targets), bool)
            chosen = []
            while uncovered.any():
                gain = covers[:, uncovered].sum(1)
                best = np.flatnonzero(gain == gain.max())
                j = int(rng.choice(best))
                chosen.append(cands[j])
                uncovered &= ~covers[j]
                if tickets is not None and len(chosen) >= len(tickets):
                    break
            if not uncovered.any() and (tickets is None or len(chosen) < len(tickets)):
                tickets = chosen
    arr = np.array([[pool[i] for i in tk] for tk in tickets], dtype=int)
    return arr


def verify(pool: list[int], tickets: np.ndarray, t: int, k: int) -> bool:
    """Wyczerpujące sprawdzenie gwarancji na wszystkich k-podzbiorach puli."""
    sets = [set(x) for x in np.asarray(tickets).tolist()]
    return all(any(len(s & set(sub)) >= t for s in sets) for sub in combinations(sorted(pool), k))


def full_system_size(m: int) -> int:
    return comb(m, K)
