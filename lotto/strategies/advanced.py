"""Strategie z etapu 5: pary, Markow, model ML, „odkryte” anomalie, filtry rozkładu, anty-popularność."""
from __future__ import annotations

import numpy as np

from lotto.analysis import ml as mlmod
from lotto.analysis import popularity
from lotto.analysis.data import K, N, DrawData, quiet_fp
from lotto.analysis.detectors import feature_values
from lotto.strategies.base import Param, Strategy, random_tickets, register, tickets_from_pool

WINDOW = Param("window", "Okno (ostatnich losowań)", 300, 20, 5000)
POOL = Param("pool", "Pula liczb", 12, 6, 49)


def _jitter(rng, n=N):
    return rng.random(n) * 1e-6


@register
class PairsStrategy(Strategy):
    name = "pairs"
    label = "Częste pary"
    description = ("Zakłady budowane z par liczb, które najczęściej padały razem w ostatnim oknie. "
                   "Testuje strukturę wewnątrz kombinacji (5.3).")
    params = [WINDOW]

    def generate(self, history, n, rng):
        Xi = history.X[-self.p["window"]:].astype(np.int32)
        C = (Xi.T @ Xi).astype(float)
        np.fill_diagonal(C, 0)
        C += rng.random(C.shape) * 1e-3
        out, seen = [], set()
        for _ in range(20 * n):
            if len(out) == n:
                break
            # start: losowa para spośród 30 najczęstszych, potem zachłannie liczba najsilniej związana z wybranymi
            iu = np.triu_indices(N, 1)
            top = np.argsort(-C[iu])[:30]
            k = rng.choice(top)
            chosen = [iu[0][k], iu[1][k]]
            while len(chosen) < K:
                score = C[chosen].sum(0)
                score[chosen] = -np.inf
                chosen.append(int(np.argmax(score + rng.random(N) * C.mean() * 0.5)))
            t = tuple(sorted(np.array(chosen) + 1))
            if t not in seen:
                seen.add(t)
                out.append(t)
        while len(out) < n:
            out.append(tuple(random_tickets(1, rng)[0]))
        return np.array(out)


@register
class MarkovStrategy(Strategy):
    name = "markov"
    label = "Łańcuch Markowa"
    description = ("Liczby, które w historii najczęściej padały w losowaniu następującym po losowaniu "
                   "z liczbami z ostatniego wyniku. Testuje zależność od poprzedniego losowania (5.2).")
    params = [WINDOW, POOL]

    def generate(self, history, n, rng):
        Xi = history.X[-self.p["window"]:].astype(np.int32)
        T = (Xi[:-1].T @ Xi[1:]).astype(float)
        rate = T / np.maximum(Xi[:-1].sum(0), 1)[:, None]      # P(j w t | i w t-1)
        last = history.X[-1]
        score = rate[last].mean(0) + _jitter(rng)
        return tickets_from_pool(np.argsort(-score)[: self.p["pool"]] + 1, n, rng)


@register
class MLStrategy(Strategy):
    name = "ml"
    label = "Model ML (regresja logistyczna)"
    description = ("Model z etapu 3 (częstości w oknach, przerwy, poprzednie losowania) uczony na historii; "
                   "typuje liczby o najwyższym przewidywanym prawdopodobieństwie.")
    params = [POOL, Param("refit", "Douczanie co (losowań)", 100, 10, 1000)]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._key, self._w = None, None

    @quiet_fp
    def _scores(self, history: DrawData) -> np.ndarray:
        key = len(history) // self.p["refit"]
        X = np.asarray(history.X)
        F = mlmod.features(np.vstack([X, np.zeros((1, N), bool)]))   # cechy także dla następnego losowania
        if key != self._key:
            rows = np.arange(len(X)) >= mlmod.WARMUP
            self._w = mlmod._fit(F[:-1][rows].reshape(-1, F.shape[2]), X[rows].reshape(-1).astype(float))
            self._key = key
        return self._w[0] + F[-1] @ self._w[1:]

    def generate(self, history, n, rng):
        if len(history) <= mlmod.WARMUP + 10:
            return random_tickets(n, rng)
        score = self._scores(history) + _jitter(rng)
        return tickets_from_pool(np.argsort(-score)[: self.p["pool"]] + 1, n, rng)


@register
class BalancedStrategy(Strategy):
    name = "balanced"
    label = "Zrównoważone kombinacje"
    description = ("Losowe zakłady odfiltrowane do typowych wartości cech (suma, parzyste, niskie, kolejne). "
                   "Popularna rada poradników; przy H0 nie zmienia szansy trafienia.")
    params = [Param("coverage", "Zostaw środkowe % rozkładu sumy", 50, 10, 100)]

    def generate(self, history, n, rng):
        lo_q = (100 - self.p["coverage"]) / 200
        cand = random_tickets(max(50 * n, 2000), rng)
        f = feature_values(cand)
        s_lo, s_hi = np.quantile(f["sum"], [lo_q, 1 - lo_q])
        ok = ((f["sum"] >= s_lo) & (f["sum"] <= s_hi) & (f["even"] >= 2) & (f["even"] <= 4)
              & (f["low"] >= 2) & (f["low"] <= 4) & (f["consecutive"] <= 1))
        good = cand[ok]
        return good[:n] if len(good) >= n else np.vstack([good, cand[~ok][: n - len(good)]])


@register
class AntiPopularStrategy(Strategy):
    name = "anti_popular"
    label = "Niepopularne kombinacje"
    description = ("Zakłady z liczb i kombinacji, które inni gracze typują najrzadziej (model popularności "
                   "z liczby zwycięzców, uczony tylko na przeszłości). Szansa trafienia ta sama, "
                   "ale przy trafieniu pula jest dzielona z mniejszą liczbą osób.")
    params = [Param("candidates", "Kandydatów do wyboru", 20000, 1000, 200000),
              Param("max_overlap", "Maks. wspólnych liczb między zakładami", 3, 0, 5)]

    def __init__(self, provider: popularity.Provider | None = None, **kw):
        super().__init__(**kw)
        self.provider = provider or popularity.Provider()

    def generate(self, history, n, rng):
        model = self.provider.model(history)
        if model is None:
            return random_tickets(n, rng)
        cand = random_tickets(self.p["candidates"], rng)
        score = model.score(cand, history.numbers[-1])
        out = []
        for i in np.argsort(score):
            t = cand[i]
            if all(len(np.intersect1d(t, o)) <= self.p["max_overlap"] for o in out):
                out.append(t)
                if len(out) == n:
                    break
        while len(out) < n:
            out.append(cand[np.argsort(score)[len(out)]])
        return np.array(out)


@register
class DiscoveredStrategy(Strategy):
    name = "discovered"
    label = "Odkryte anomalie"
    description = ("Wykorzystuje anomalie wykryte na danych treningowych w raporcie analizy (etap 3): "
                   "faworyzuje liczby i grupy kul o istotnie wyższej częstości oraz powtórki, jeśli wykryto. "
                   "Gdy nie wykryto żadnej anomalii, typuje losowo.")
    params = [POOL]

    def __init__(self, report: dict | None = None, **kw):
        super().__init__(**kw)
        if report is None:
            from lotto.analysis import protocol
            report = protocol.load_report() or {"hypotheses": []}
        alpha = (report.get("params") or {}).get("alpha", 0.05)
        # tylko hipotezy wybrane na TRAIN (q ≤ α): wolno ich użyć w okresie testowym
        self.used = [h for h in report["hypotheses"] if h.get("train") and h["train"]["q"] <= alpha]
        self.weights = np.zeros(N)
        self.repeat_bonus = 0.0
        from lotto.analysis.detectors import PHYSICAL_GROUPS
        for h in self.used:
            eff = h["train"]["effect"] or 0
            if h["id"].startswith("freq.") and h["id"] != "freq.all":
                self.weights[int(h["id"][5:]) - 1] += eff
            elif h["id"].startswith("group."):
                nums = PHYSICAL_GROUPS[h["id"][6:]][1]
                self.weights[np.array(nums) - 1] += eff
            elif h["id"] == "lag.01":
                self.repeat_bonus = eff

    def generate(self, history, n, rng):
        if not self.weights.any() and not self.repeat_bonus:
            return random_tickets(n, rng)
        score = self.weights + self.repeat_bonus * history.X[-1] + _jitter(rng)
        return tickets_from_pool(np.argsort(-score)[: self.p["pool"]] + 1, n, rng)
