"""Model popularności liczb: które liczby i kombinacje gracze typują najczęściej.

Wygrane za 4, 5 i 6 są dzielone między zwycięzców. Typując kombinacje rzadko wybierane
przez innych, nie zwiększamy szansy trafienia, ale przy trafieniu dzielimy pulę z mniejszą
liczbą osób.

Sygnał: liczba zwycięzców z trójką (W3). Gdy wylosowane liczby są popularne, więcej
graczy trafia trójkę. Wielkość sprzedaży usuwamy, porównując log(W3) z medianą sąsiednich
losowań, i dodając liczbę kolejnych kumulacji (wysoka kumulacja napędza sprzedaż).

    r_t = log W3_t − mediana(log W3 sąsiadów)  ≈  Σ_{i ∈ losowanie} β_i + γ·cechy + ε

β_i > 0: liczba popularna. Wynik modelu dla zakładu: suma β jego liczb + γ·cechy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from lotto.analysis.data import N, DrawData, quiet_fp

EXTRA = ["pary kolejnych liczb", "liczby z poprzedniego losowania", "log(1 + kumulacje z rzędu)"]


@dataclass
class PrizeFrame:
    """Losowania z danymi o wygranych (indeksy wierszy w DrawData)."""
    rows: np.ndarray       # (m,) indeksy w DrawData
    W3: np.ndarray
    W4: np.ndarray
    A4: np.ndarray
    A5: np.ndarray
    rollovers: np.ndarray  # ile losowań z rzędu przed tym bez szóstki


def prize_frame(d: DrawData, prizes: dict[int, dict[int, tuple[int, float]]]) -> PrizeFrame:
    rows, W3, W4, A4, A5, roll = [], [], [], [], [], []
    run = 0
    for i, no in enumerate(d.draw_no):
        pz = prizes.get(int(no))
        if not pz or not all(k in pz for k in (3, 4, 5, 6)):
            run = 0
            continue
        if pz[3][0] > 0 and pz[4][0] > 0:
            rows.append(i)
            W3.append(pz[3][0]); W4.append(pz[4][0]); A4.append(pz[4][1]); A5.append(pz[5][1])
            roll.append(run)
        run = run + 1 if pz[6][0] == 0 else 0
    f = lambda x: np.array(x, float)  # noqa: E731
    return PrizeFrame(np.array(rows, int), f(W3), f(W4), f(A4), f(A5), f(roll))


def rolling_baseline(y: np.ndarray, half: int = 10) -> np.ndarray:
    """Mediana sąsiadów (±half), bez samego punktu."""
    out = np.empty_like(y)
    for i in range(len(y)):
        nb = np.r_[y[max(0, i - half):i], y[i + 1:i + 1 + half]]
        out[i] = np.median(nb) if len(nb) else y[i]
    return out


def combo_features(numbers: np.ndarray, prev: np.ndarray | None) -> np.ndarray:
    """(n, 2) cechy kombinacji: pary kolejnych liczb, liczby z poprzedniego losowania."""
    s = np.sort(numbers, axis=1)
    consec = (np.diff(s, axis=1) == 1).sum(1)
    if prev is None:
        rep = np.zeros(len(s))
    else:
        rep = (s[:, :, None] == np.asarray(prev)[:, None, :]).any(2).sum(1) if prev.ndim == 2 else np.isin(s, prev).sum(1)
    return np.c_[consec, rep].astype(float)


def design(d: DrawData, pf: PrizeFrame, sel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = pf.rows[sel]
    numbers = d.numbers[rows]
    prev = d.numbers[np.maximum(rows - 1, 0)]
    Xn = d.X[rows].astype(float)
    Xc = combo_features(numbers, prev)
    Xr = np.log1p(pf.rollovers[sel])[:, None]
    y = np.log(pf.W3[sel])
    target = y - rolling_baseline(y)
    return np.hstack([Xn, Xc, Xr]), target


@dataclass
class Model:
    beta: np.ndarray       # (49,) popularność liczby (średnia 0)
    gamma: np.ndarray      # (3,) cechy dodatkowe
    n_draws: int

    @quiet_fp
    def score(self, tickets: np.ndarray, prev: np.ndarray | None = None) -> np.ndarray:
        """Przewidywana popularność zakładów (log względnej liczby graczy z tymi liczbami)."""
        t = np.asarray(tickets)
        s = self.beta[t - 1].sum(1)
        c = combo_features(t, prev)
        return s + c @ self.gamma[:2]

    def to_dict(self) -> dict:
        return {"beta": self.beta.tolist(), "gamma": dict(zip(EXTRA, self.gamma.tolist())), "n_draws": self.n_draws}


@quiet_fp
def fit(d: DrawData, pf: PrizeFrame, sel: np.ndarray | None = None, l2: float = 3.0) -> Model:
    sel = np.ones(len(pf.rows), bool) if sel is None else sel
    X, y = design(d, pf, sel)
    Xc = X - X.mean(0)
    yc = y - y.mean()
    w = np.linalg.solve(Xc.T @ Xc + l2 * np.eye(X.shape[1]), Xc.T @ yc)
    beta = w[:N] - w[:N].mean()
    return Model(beta, w[N:], int(sel.sum()))


@quiet_fp
def evaluate(d: DrawData, pf: PrizeFrame, test_since: date) -> dict:
    """Model z danych do test_since, sprawdzony na późniejszych losowaniach."""
    dates = d.dates[pf.rows]
    tr = dates < np.datetime64(test_since, "D")
    te = ~tr
    m = fit(d, pf, tr)
    X, y = design(d, pf, te)
    pred = X[:, :N] @ m.beta + X[:, N:] @ m.gamma
    # sama popularność liczb i kombinacji (bez efektu kumulacji na sprzedaż)
    pred_combo = X[:, :N] @ m.beta + X[:, N:N + 2] @ m.gamma[:2]
    y_adj = y - X[:, N + 2] * m.gamma[2]
    # model ocenia tylko liczby i cechy kombinacji; wyraz wolny i trend usuwa mediana sąsiadów
    resid = y - y.mean()
    r2 = 1 - ((resid - (pred - pred.mean())) ** 2).sum() / (resid ** 2).sum()
    corr = float(np.corrcoef(pred, y)[0, 1])
    corr_combo = float(np.corrcoef(pred_combo, y_adj)[0, 1])
    # czy wygrana za 4 i 5 jest wyższa, gdy wylosowane liczby są niepopularne (wg modelu z train)?
    q = np.quantile(pred_combo, [0.2, 0.8])
    lo, hi = pred_combo <= q[0], pred_combo >= q[1]
    rows = pf.rows[te]
    A4, A5 = pf.A4[te], pf.A5[te]
    n_test = int(te.sum())
    # jak wygrana za 4 zależy od popularności wylosowanych liczb (poza próbą): log A4 = a + b·wynik
    slope4 = float(np.polyfit(pred_combo, np.log(A4), 1)[0])
    slope5 = float(np.polyfit(pred_combo, np.log(A5), 1)[0])
    # test permutacyjny korelacji (losowania testowe niezależne od modelu z train)
    rng = np.random.default_rng(0)
    null = np.array([np.corrcoef(rng.permutation(pred_combo), y_adj)[0, 1] for _ in range(2000)])
    return {
        "n_train": int(tr.sum()), "n_test": n_test,
        "r2_test": float(r2), "corr_test": corr,
        "corr_combo_test": corr_combo,
        "p_corr_combo": float((1 + (null >= corr_combo).sum()) / (1 + len(null))),
        "prize4_unpopular": float(np.median(A4[lo])), "prize4_popular": float(np.median(A4[hi])),
        "prize5_unpopular": float(np.median(A5[lo])), "prize5_popular": float(np.median(A5[hi])),
        "w3_ratio_popular_vs_unpopular": float(np.exp(np.median(y_adj[hi]) - np.median(y_adj[lo]))),
        "first_test_draw": int(d.draw_no[rows[0]]) if n_test else None,
        "slope_log_prize4": slope4, "slope_log_prize5": slope5,
        # zakres wyników wylosowanych kombinacji: poza nim zależności nie obserwowaliśmy (bez ekstrapolacji)
        "score_range": [float(np.quantile(pred_combo, 0.01)), float(np.quantile(pred_combo, 0.99))],
        "model_train": m.to_dict(),
    }


@lru_cache(maxsize=1)
def _db_prizes() -> dict:
    from lotto.data import db
    conn = db.connect()
    try:
        out: dict[int, dict[int, tuple[int, float]]] = {}
        for r in conn.execute("SELECT draw_no, tier, winners, amount FROM prizes"):
            out.setdefault(r["draw_no"], {})[r["tier"]] = (r["winners"], r["amount"])
        return out
    finally:
        conn.close()


def clear_cache() -> None:
    _db_prizes.cache_clear()


class Provider:
    """Model popularności dopasowany wyłącznie do losowań z historii (bez wglądu w przyszłość).

    Dopasowanie co `refit` losowań (szybkość backtestu).
    """

    def __init__(self, prizes: dict | None = None, refit: int = 50, min_draws: int = 150):
        self.prizes = prizes
        self.refit = refit
        self.min_draws = min_draws
        self._key = None
        self._model: Model | None = None

    def model(self, history: DrawData) -> Model | None:
        key = len(history) // self.refit
        if key != self._key:
            prizes = self.prizes if self.prizes is not None else _db_prizes()
            pf = prize_frame(history, prizes)
            self._model = fit(history, pf) if len(pf.rows) >= self.min_draws else None
            self._key = key
        return self._model
