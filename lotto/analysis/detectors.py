"""Detektory anomalii: każdy testuje inny sposób, w jaki losowania mogłyby odbiegać od H0.

H0: każde losowanie to 6 z 49 bez zwracania, jednostajnie i niezależnie od innych.

Dwa rodzaje detektorów:
- analityczne: zwracają wartość p ze znanego rozkładu (chi-kwadrat, normalny, Kołmogorowa),
- Monte Carlo: zwracają tylko statystykę; wartość p liczy protokół, porównując ją
  ze statystyką na losowaniach symulowanych zgodnie z H0 (te same daty, ta sama liczba losowań).

Uwaga o zależności liczb w jednym losowaniu: wskaźniki trafień liczb nie są niezależne
(suma = 6), kowariancja = -p(1-p)/48. Stąd czynnik 48/49 przy sumowaniu kwadratów z-score'ów:
48/49 · Σ z_i² ~ χ²(48).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Callable

import numpy as np
from scipy import stats

from lotto.analysis.data import K, N, P, DrawData, simulate

G_BIAS = "5.1 Obciążenie liczb i dryf w czasie"
G_DEP = "5.2 Zależność od poprzednich losowań"
G_STRUCT = "5.3 Struktura kombinacji i kolejność kul"
G_CTX = "5.4 Kontekst losowania"
G_ML = "5.5 Przewidywalność modelem"

DEP = 48 / 49           # korekta na zależność liczb w jednym losowaniu
HYPER_MEAN = K * K / N  # średnia liczba wspólnych liczb dwóch niezależnych losowań
HYPER_VAR = K * (K / N) * ((N - K) / N) * ((N - K) / (N - 1))


@dataclass
class Result:
    id: str
    group: str
    name: str
    method: str
    stat: float
    p: float
    effect: float | None = None
    effect_label: str = ""
    n: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("stat", "p", "effect"):
            if d[k] is not None:
                d[k] = float(d[k])
        return d


# --- 5.1 obciążenie i dryf ----------------------------------------------------

def frequency(d: DrawData) -> list[Result]:
    n = len(d)
    c = d.X.sum(0)
    e = n * P
    z = (c - e) / np.sqrt(n * P * (1 - P))
    chi = DEP * float((z ** 2).sum())
    out = [Result("freq.all", G_BIAS, "Jednorodność częstości wszystkich liczb", "χ² analityczny",
                  chi, stats.chi2.sf(chi, N - 1), float(np.abs(c / e - 1).max()),
                  "największe względne odchylenie liczby", n)]
    for i in range(N):
        out.append(Result(f"freq.{i + 1:02d}", G_BIAS, f"Częstość liczby {i + 1}", "z analityczny",
                          float(z[i]), 2 * stats.norm.sf(abs(z[i])), float(c[i] / e - 1),
                          "względne odchylenie od oczekiwanej częstości", n))
    return out


def drift(d: DrawData) -> list[Result]:
    """Czy częstość liczby zmienia się w czasie (most Browna: max |CUSUM| ~ Kołmogorow)."""
    n = len(d)
    out = []
    for i in range(N):
        x = d.X[:, i].astype(float)
        r = x.mean()
        if r in (0, 1):
            continue
        s = np.cumsum(x - r)
        k = int(np.abs(s).argmax())
        D = float(np.abs(s).max() / np.sqrt(n * r * (1 - r)))
        out.append(Result(f"drift.{i + 1:02d}", G_BIAS, f"Dryf częstości liczby {i + 1} w czasie",
                          "CUSUM / Kołmogorow", D, stats.kstwobign.sf(D), D,
                          "znormalizowane max odchylenie skumulowane", n,
                          {"change_at": str(d.dates[k])}))
    return out


def homogeneity(d: DrawData, labels: np.ndarray, hid: str, group: str, name: str, min_size: int = 30) -> list[Result]:
    """Czy częstości liczb są takie same we wszystkich grupach losowań (era, dzień tygodnia…)."""
    keep = np.isin(labels, [g for g in np.unique(labels) if (labels == g).sum() >= min_size])
    d, labels = d.subset(keep), labels[keep]
    groups = np.unique(labels)
    if len(groups) < 2:
        return []
    r = d.X.mean(0)
    chi = 0.0
    for g in groups:
        m = labels == g
        nk = m.sum()
        chi += float((((d.X[m].sum(0) - nk * r) ** 2) / (nk * r * (1 - r))).sum())
    chi *= DEP
    df = (N - 1) * (len(groups) - 1)
    return [Result(hid, group, name, "χ² analityczny", chi, stats.chi2.sf(chi, df), chi / df,
                   "χ²/df (1 = zgodnie z H0)", len(d), {"groups": [str(g) for g in groups]})]


def eras(d: DrawData) -> list[Result]:
    years = d.dates.astype("datetime64[Y]").astype(int) + 1970
    return homogeneity(d, (years // 10) * 10, "drift.decades", G_BIAS,
                       "Różnice częstości liczb między dekadami")


# Grupy kul, które mogłyby różnić się fizycznie (ilość farby, cyfry) albo statystycznie.
PHYSICAL_GROUPS = {
    "single": ("jednocyfrowe (1–9)", list(range(1, 10))),
    "low": ("niskie (1–24)", list(range(1, 25))),
    "even": ("parzyste", list(range(2, 50, 2))),
    "digit8": ("z cyfrą 8 (8, 18, 28, 38, 48)", [8, 18, 28, 38, 48]),
    "digit0": ("z cyfrą 0 (10, 20, 30, 40)", [10, 20, 30, 40]),
}


def ball_groups(d: DrawData) -> list[Result]:
    n = len(d)
    out = []
    for key, (label, nums) in PHYSICAL_GROUPS.items():
        g = len(nums)
        s = d.X[:, np.array(nums) - 1].sum()
        mean = n * K * g / N
        var = n * K * (g / N) * (1 - g / N) * ((N - K) / (N - 1))
        z = (s - mean) / np.sqrt(var)
        out.append(Result(f"group.{key}", G_BIAS, f"Grupa kul: {label}", "z analityczny",
                          float(z), 2 * stats.norm.sf(abs(z)), float(s / mean - 1),
                          "względne odchylenie liczby trafień grupy", n))
    return out


# --- 5.2 zależność od poprzednich losowań -------------------------------------

def overlaps(d: DrawData, lag: int) -> np.ndarray:
    return (d.X[lag:] & d.X[:-lag]).sum(1)


def lag_overlap(d: DrawData, max_lag: int = 20) -> list[Result]:
    """Liczba wspólnych liczb losowań odległych o `lag`; H0: średnio 36/49.

    Nakładania o_t i o_{t+lag} są niezależne przy H0 (rozkład o_t nie zależy od
    wspólnego losowania), więc test z jest dokładny asymptotycznie.
    """
    out = []
    for lag in range(1, max_lag + 1):
        o = overlaps(d, lag)
        if len(o) < 30:
            break
        z = (o.mean() - HYPER_MEAN) / np.sqrt(HYPER_VAR / len(o))
        out.append(Result(f"lag.{lag:02d}", G_DEP, f"Wspólne liczby z losowaniem sprzed {lag}",
                          "z analityczny", float(z), 2 * stats.norm.sf(abs(z)),
                          float(o.mean() / HYPER_MEAN - 1), "względna zmiana średniej liczby powtórzeń", len(o)))
    return out


def repeat_distribution(d: DrawData) -> list[Result]:
    o = overlaps(d, 1)
    pmf = stats.hypergeom(N, K, K).pmf(np.arange(K + 1))
    obs = np.array([(o == k).sum() for k in range(3)] + [(o >= 3).sum()])
    exp = len(o) * np.array([*pmf[:3], pmf[3:].sum()])
    chi = float(((obs - exp) ** 2 / exp).sum())
    return [Result("repeat.dist", G_DEP, "Rozkład liczby powtórzeń z poprzedniego losowania (0/1/2/3+)",
                   "χ² analityczny", chi, stats.chi2.sf(chi, 3), None, "", len(o),
                   {"observed": obs.tolist(), "expected": exp.tolist()})]


# --- 5.3 struktura kombinacji i kolejność kul ---------------------------------

FEATURES = {
    "sum": "suma liczb",
    "even": "liczba parzystych",
    "low": "liczba niskich (1–24)",
    "consecutive": "liczba par kolejnych liczb",
    "range": "rozpiętość (max − min)",
}


def feature_values(numbers: np.ndarray) -> dict[str, np.ndarray]:
    diffs = np.diff(numbers, axis=1)
    return {
        "sum": numbers.sum(1),
        "even": (numbers % 2 == 0).sum(1),
        "low": (numbers <= 24).sum(1),
        "consecutive": np.minimum((diffs == 1).sum(1), 3),
        "range": numbers[:, -1] - numbers[:, 0],
    }


@lru_cache(maxsize=1)
def feature_reference(n: int = 2_000_000, seed: int = 12345) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Rozkłady cech przy H0 (z dużej symulacji): dla każdej cechy (krawędzie przedziałów, prawdopodobieństwa)."""
    X, _ = simulate(n, np.random.default_rng(seed))
    nums = np.sort(np.argsort(~X, axis=1, kind="stable")[:, :K] + 1, axis=1)
    out = {}
    for name, v in feature_values(nums).items():
        if name in ("sum", "range"):
            edges = np.unique(np.quantile(v, np.linspace(0, 1, 13)))
            edges[-1] += 1
        else:
            edges = np.arange(v.min(), v.max() + 2)
        probs = np.histogram(v, edges)[0] / n
        out[name] = (edges, probs)
    return out


def combination_features(d: DrawData) -> list[Result]:
    ref = feature_reference()
    n = len(d)
    out = []
    for name, v in feature_values(d.numbers).items():
        edges, probs = ref[name]
        obs = np.histogram(np.clip(v, edges[0], edges[-1] - 1), edges)[0].astype(float)
        exp = probs * n
        # łączymy przedziały o oczekiwanej liczności < 5
        o2, e2, acc_o, acc_e = [], [], 0.0, 0.0
        for o, e in zip(obs, exp):
            acc_o += o; acc_e += e
            if acc_e >= 5:
                o2.append(acc_o); e2.append(acc_e); acc_o = acc_e = 0.0
        if acc_e and e2:
            o2[-1] += acc_o; e2[-1] += acc_e
        o2, e2 = np.array(o2), np.array(e2)
        chi = float(((o2 - e2) ** 2 / e2).sum())
        mean_ref = float((probs * (edges[:-1] if name not in ("sum", "range") else (edges[:-1] + edges[1:]) / 2)).sum())
        out.append(Result(f"feature.{name}", G_STRUCT, f"Rozkład cechy kombinacji: {FEATURES[name]}",
                          "χ² zgodności", chi, stats.chi2.sf(chi, len(o2) - 1),
                          float(v.mean()), f"średnia (H0 ≈ {mean_ref:.2f})", n))
    return out


def ball_order(d: DrawData) -> list[Result]:
    """Czy kula wylosowana jako k-ta ma jednostajny rozkład wartości 1..49."""
    o = d.order[d.has_order]
    if len(o) < 100:
        return []
    out = []
    for k in range(K):
        c = np.bincount(o[:, k], minlength=N + 1)[1:]
        e = len(o) / N
        chi = float(((c - e) ** 2 / e).sum())
        out.append(Result(f"order.pos{k + 1}", G_STRUCT, f"Wartości kul wylosowanych jako {k + 1}.",
                          "χ² analityczny", chi, stats.chi2.sf(chi, N - 1),
                          float(o[:, k].mean()), "średnia wartość kuli (H0 = 25)", len(o)))
    # czy średnia wartość zależy od pozycji (np. lżejsze kule wypadają wcześniej)
    h, p = stats.kruskal(*[o[:, k] for k in range(K)])
    out.append(Result("order.trend", G_STRUCT, "Zależność wartości kuli od kolejności losowania",
                      "Kruskal–Wallis", float(h), float(p), None, "", len(o)))
    return out


# --- 5.4 kontekst -------------------------------------------------------------

def context(d: DrawData) -> list[Result]:
    wd = (d.dates.astype("datetime64[D]").astype(int) + 3) % 7   # 0 = poniedziałek
    months = d.dates.astype("datetime64[M]").astype(int) % 12 + 1
    return [
        *homogeneity(d, wd, "ctx.weekday", G_CTX, "Różnice częstości liczb między dniami tygodnia"),
        *homogeneity(d, months, "ctx.month", G_CTX, "Różnice częstości liczb między miesiącami"),
    ]


ANALYTIC: list[Callable[[DrawData], list[Result]]] = [
    frequency, drift, eras, ball_groups, lag_overlap, repeat_distribution,
    combination_features, ball_order, context,
]


# --- Monte Carlo: statystyki globalne bez prostego rozkładu ---------------------

def gap_stat(d: DrawData) -> float:
    """χ² rozkładu przerw (ile losowań do ponownego pojawienia się liczby) wobec geometrycznego."""
    gaps = np.concatenate([np.diff(np.flatnonzero(d.X[:, i])) for i in range(N)])
    edges = np.arange(1, 42)
    obs = np.histogram(np.minimum(gaps, 41), np.append(edges, 42))[0]
    pk = (1 - P) ** (edges - 1) * P
    pk[-1] = (1 - P) ** 40
    exp = pk * len(gaps)
    return float(((obs - exp) ** 2 / exp).sum())


def markov_stat(d: DrawData) -> float:
    """χ² tablicy przejść: liczba i w losowaniu t-1 → liczba j w losowaniu t."""
    A = d.X[:-1].astype(np.int32)
    B = d.X[1:].astype(np.int32)
    T = A.T @ B
    E = np.outer(A.sum(0), B.sum(0)) / len(A)
    return float(((T - E) ** 2 / E).sum())


_IU = np.triu_indices(N, 1)
PAIR_P = K * (K - 1) / (N * (N - 1))


def pair_stats(d: DrawData) -> tuple[float, float]:
    Xi = d.X.astype(np.int32)
    C = (Xi.T @ Xi)[_IU]
    e = len(d) * PAIR_P
    z = (C - e) / np.sqrt(e * (1 - PAIR_P))
    return float((z ** 2).sum()), float(np.abs(z).max())


def mc_statistics(d: DrawData) -> dict[str, float]:
    """Wszystkie statystyki Monte Carlo naraz (liczone też na każdej symulacji)."""
    chi, mx = pair_stats(d)
    return {"gaps": gap_stat(d), "markov": markov_stat(d), "pairs.chi": chi, "pairs.max": mx}


MONTE_CARLO: dict[str, tuple[str, str]] = {
    "gaps": (G_DEP, "Rozkład przerw między wystąpieniami liczby (vs geometryczny)"),
    "markov": (G_DEP, "Przejścia liczba → liczba między kolejnymi losowaniami (łańcuch Markowa)"),
    "pairs.chi": (G_STRUCT, "Częstości wszystkich 1176 par liczb"),
    "pairs.max": (G_STRUCT, "Najbardziej odstająca para liczb"),
}
