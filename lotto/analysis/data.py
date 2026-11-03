"""Losowania w postaci macierzy oraz generator losowań zgodnych z H0 (i z obciążeniem)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from lotto.data.validate import Draw

N = 49
K = 6
P = K / N   # szansa, że dana liczba padnie w losowaniu


def quiet_fp(fn):
    """numpy + Accelerate (macOS) zgłasza fałszywe flagi FP przy mnożeniu macierzy float64
    (wyniki są poprawne). Wyciszamy je i jawnie sprawdzamy, że wynik liczbowy jest skończony."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            out = fn(*a, **kw)
        arrays = [out] if isinstance(out, np.ndarray) else [v for v in getattr(out, "__dict__", {}).values()
                                                             if isinstance(v, np.ndarray)]
        for arr in arrays:
            if arr.dtype.kind == "f" and not np.isfinite(arr).all():
                raise FloatingPointError(f"{fn.__name__}: wynik zawiera wartości nieskończone")
        return out
    return wrapper


@dataclass
class DrawData:
    draw_no: np.ndarray        # (n,)
    dates: np.ndarray          # (n,) datetime64[D]
    X: np.ndarray              # (n, 49) bool: czy liczba i+1 padła
    order: np.ndarray          # (n, 6) int: kolejność kul (wartości 1..49), -1 gdy nieznana

    def __len__(self) -> int:
        return len(self.draw_no)

    def subset(self, mask: np.ndarray) -> "DrawData":
        return DrawData(self.draw_no[mask], self.dates[mask], self.X[mask], self.order[mask])

    def head(self, t: int) -> "DrawData":
        """Pierwsze t losowań jako widoki tylko do odczytu (historia dla strategii)."""
        parts = [self.draw_no[:t], self.dates[:t], self.X[:t], self.order[:t]]
        for a in parts:
            a.flags.writeable = False
        return DrawData(*parts)

    @property
    def has_order(self) -> np.ndarray:
        return self.order[:, 0] > 0

    @property
    def numbers(self) -> np.ndarray:
        """(n, 6) posortowane liczby 1..49."""
        return np.sort(np.argsort(~self.X, axis=1, kind="stable")[:, :K] + 1, axis=1)


def from_draws(draws: list[Draw]) -> DrawData:
    n = len(draws)
    X = np.zeros((n, N), dtype=bool)
    order = np.full((n, K), -1, dtype=np.int16)
    for i, d in enumerate(draws):
        X[i, np.array(d.numbers) - 1] = True
        if d.order:
            order[i] = d.order
    return DrawData(
        np.array([d.draw_no for d in draws]),
        np.array([np.datetime64(d.date, "D") for d in draws]),
        X, order,
    )


def split(d: DrawData, test_since: date) -> tuple[DrawData, DrawData]:
    mask = d.dates < np.datetime64(test_since, "D")
    return d.subset(mask), d.subset(~mask)


def simulate(n: int, rng: np.random.Generator, weights: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """n losowań 6 z 49 bez zwracania; `weights` (49,) daje obciążone kule.

    Sztuczka Gumbela: top-6 z log(w) + Gumbel to losowanie sekwencyjne bez zwracania
    z prawdopodobieństwami proporcjonalnymi do w, a kolejność kluczy to kolejność losowania.
    """
    keys = rng.gumbel(size=(n, N))
    if weights is not None:
        keys += np.log(weights)
    top = np.argpartition(-keys, K, axis=1)[:, :K]
    top_keys = np.take_along_axis(keys, top, axis=1)
    order = np.take_along_axis(top, np.argsort(-top_keys, axis=1), axis=1) + 1
    X = np.zeros((n, N), dtype=bool)
    np.put_along_axis(X, top, True, axis=1)
    return X, order.astype(np.int16)


def simulate_like(d: DrawData, rng: np.random.Generator, weights: np.ndarray | None = None) -> DrawData:
    """Losowania zgodne z H0 o tych samych datach i dostępności kolejności co `d`."""
    X, order = simulate(len(d), rng, weights)
    order[~d.has_order] = -1
    return DrawData(d.draw_no, d.dates, X, order)
