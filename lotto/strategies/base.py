"""Interfejs strategii.

Strategia dostaje historię (losowania przed losowaniem, które typuje, tylko do odczytu)
i zwraca `n` zakładów: tablicę (n, 6) liczb 1..49, bez powtórzeń w zakładzie.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from lotto.analysis.data import K, N, DrawData


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: int | float
    min: int | float
    max: int | float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class Strategy:
    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[list[Param]] = []

    def __init__(self, **kwargs):
        self.p = {}
        for prm in self.params:
            v = kwargs.get(prm.name, prm.default)
            v = type(prm.default)(v)
            if not prm.min <= v <= prm.max:
                raise ValueError(f"{prm.label}: wartość {v} poza zakresem {prm.min}–{prm.max}")
            self.p[prm.name] = v
        unknown = set(kwargs) - {prm.name for prm in self.params}
        if unknown:
            raise ValueError(f"nieznane parametry: {sorted(unknown)}")

    def generate(self, history: DrawData, n: int, rng: np.random.Generator) -> np.ndarray:
        raise NotImplementedError

    @classmethod
    def describe(cls) -> dict:
        return {"name": cls.name, "label": cls.label, "description": cls.description,
                "params": [p.to_dict() for p in cls.params]}


REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    REGISTRY[cls.name] = cls
    return cls


def get(name: str, **params) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"nieznana strategia: {name}")
    return REGISTRY[name](**params)


def random_tickets(n: int, rng: np.random.Generator) -> np.ndarray:
    return np.sort(np.argsort(rng.random((n, N)), axis=1)[:, :K] + 1, axis=1)


def tickets_from_pool(pool: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """n zakładów z puli liczb (uporządkowanej od najlepszej).

    Pierwszy zakład to 6 najlepszych liczb; kolejne to losowe, różne od siebie kombinacje z puli.
    """
    pool = np.asarray(pool)
    if len(pool) < K:
        raise ValueError("pula musi mieć co najmniej 6 liczb")
    out = [np.sort(pool[:K])]
    seen = {tuple(out[0])}
    attempts = 0
    while len(out) < n and attempts < 50 * n:
        t = tuple(np.sort(rng.choice(pool, K, replace=False)))
        attempts += 1
        if t not in seen:
            seen.add(t)
            out.append(np.array(t))
    while len(out) < n:   # pula zbyt mała na tyle różnych zakładów: powtórki
        out.append(out[len(out) % len(seen)])
    return np.array(out[:n])
