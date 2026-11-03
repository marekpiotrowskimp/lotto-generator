"""Strategie bazowe: losowa, „gorące” i „zimne” liczby."""
from __future__ import annotations

import numpy as np

from lotto.analysis.data import N, DrawData
from lotto.strategies.base import Param, Strategy, random_tickets, register, tickets_from_pool

WINDOW = Param("window", "Okno (ostatnich losowań)", 100, 10, 2000)
POOL = Param("pool", "Pula liczb", 12, 6, 49)


@register
class RandomStrategy(Strategy):
    name = "random"
    label = "Losowa (chybił-trafił)"
    description = "Jednostajnie losowe zakłady. Punkt odniesienia: przy H0 żadna strategia nie trafia częściej."

    def generate(self, history: DrawData, n: int, rng: np.random.Generator) -> np.ndarray:
        return random_tickets(n, rng)


def _ranked(history: DrawData, window: int, hottest: bool, rng: np.random.Generator) -> np.ndarray:
    counts = history.X[-window:].sum(0).astype(float)
    counts += rng.random(N) * 1e-3   # losowe rozstrzyganie remisów
    order = np.argsort(-counts if hottest else counts)
    return order + 1


@register
class HotStrategy(Strategy):
    name = "hot"
    label = "Gorące liczby"
    description = "Liczby najczęstsze w ostatnim oknie losowań. Testuje trwałe lub dryfujące obciążenie (5.1)."
    params = [WINDOW, POOL]

    def generate(self, history, n, rng):
        return tickets_from_pool(_ranked(history, self.p["window"], True, rng)[: self.p["pool"]], n, rng)


@register
class ColdStrategy(Strategy):
    name = "cold"
    label = "Zimne liczby"
    description = "Liczby najrzadsze w ostatnim oknie („muszą wypaść”). Testuje wyrównywanie i zależność od historii (5.2)."
    params = [WINDOW, POOL]

    def generate(self, history, n, rng):
        return tickets_from_pool(_ranked(history, self.p["window"], False, rng)[: self.p["pool"]], n, rng)
