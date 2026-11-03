"""5.5 Test „czarnej skrzynki”: czy model przewiduje następne losowanie lepiej niż 6/49.

Model: regresja logistyczna na cechach z historii (częstości w oknach, przerwa,
obecność w poprzednich losowaniach), uczona na train i oceniana na test.
Wartość p: test permutacyjny. Ten sam model uczony na losowaniach w przetasowanej
kolejności (struktura w czasie zniszczona) daje rozkład wyników przy braku struktury.
"""
from __future__ import annotations

import numpy as np
from scipy import optimize

from lotto.analysis.data import K, N, P, DrawData
from lotto.analysis.detectors import G_ML, Result

WINDOWS = (10, 50, 200)
WARMUP = max(WINDOWS)
FEATURE_NAMES = [f"częstość w ostatnich {w}" for w in WINDOWS] + [
    "log(przerwa)", "w poprzednim losowaniu", "dwa losowania wcześniej"]


def features(X: np.ndarray) -> np.ndarray:
    """(n, 49, f) cechy liczby i przed losowaniem t (tylko z losowań < t)."""
    n = len(X)
    Xi = X.astype(np.int32)
    C = np.vstack([np.zeros((1, N), np.int32), np.cumsum(Xi, 0)])
    t = np.arange(n)
    cols = []
    for w in WINDOWS:
        lo = np.maximum(t - w, 0)
        cols.append((C[t] - C[lo]) / np.maximum(t - lo, 1)[:, None] - P)
    gap = np.zeros((n, N))
    last = np.full(N, -1)
    for i in range(n):
        gap[i] = np.where(last >= 0, i - last, i + 1)
        last[X[i]] = i
    cols.append(np.log(gap) - np.log(1 / P))
    prev1 = np.vstack([np.zeros((1, N)), Xi[:-1]])
    prev2 = np.vstack([np.zeros((2, N)), Xi[:-2]])
    cols += [prev1 - P, prev2 - P]
    return np.stack(cols, axis=2)


def _fit(F: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    A = np.hstack([np.ones((len(F), 1)), F])

    def loss(w):
        z = A @ w
        ll = np.logaddexp(0, z) - y * z
        reg = 0.5 * l2 * (w[1:] ** 2).sum()
        g = A.T @ (1 / (1 + np.exp(-z)) - y) + l2 * np.r_[0, w[1:]]
        return ll.sum() + reg, g

    w0 = np.r_[np.log(P / (1 - P)), np.zeros(F.shape[1])]
    return optimize.minimize(loss, w0, jac=True, method="L-BFGS-B").x


def _evaluate(X: np.ndarray, train_mask: np.ndarray) -> dict:
    # numpy + Accelerate (macOS) zgłasza fałszywe flagi FP przy mnożeniu macierzy float64;
    # wyniki są poprawne, więc wyciszamy flagi i sprawdzamy skończoność wyniku jawnie.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        out = _evaluate_inner(X, train_mask)
    if not np.isfinite([out["gain"], out["top6_hits"], *out["weights"]]).all():
        raise FloatingPointError("model zwrócił wartości nieskończone")
    return out


def _evaluate_inner(X: np.ndarray, train_mask: np.ndarray) -> dict:
    F = features(X)
    rows = np.arange(len(X)) >= WARMUP
    tr, te = rows & train_mask, rows & ~train_mask
    w = _fit(F[tr].reshape(-1, F.shape[2]), X[tr].reshape(-1).astype(float))
    Ft = F[te]
    prob = 1 / (1 + np.exp(-(w[0] + Ft @ w[1:])))
    y = X[te]
    ll_model = -(y * np.log(prob) + (~y) * np.log(1 - prob)).mean()
    ll_base = -(y * np.log(P) + (~y) * np.log(1 - P)).mean()
    top6 = np.argsort(-prob, axis=1)[:, :K]
    hits = np.take_along_axis(y, top6, axis=1).sum(1)
    return {"gain": float(ll_base - ll_model), "top6_hits": float(hits.mean()), "weights": w.tolist(),
            "n_test": int(te.sum())}


def predictability(d: DrawData, train_mask: np.ndarray, permutations: int, rng: np.random.Generator,
                   progress=None) -> Result:
    obs = _evaluate(d.X, train_mask)
    null = []
    for i in range(permutations):
        null.append(_evaluate(d.X[rng.permutation(len(d))], train_mask)["gain"])
        if progress:
            progress(i + 1, permutations)
    null = np.array(null)
    p = (1 + (null >= obs["gain"]).sum()) / (1 + permutations) if permutations else float("nan")
    return Result(
        "ml.logistic", G_ML, "Regresja logistyczna na cechach historii (vs model 6/49)", "permutacyjny",
        obs["gain"] * 1e4, float(p), obs["top6_hits"],
        f"średnio trafionych z 6 najbardziej prawdopodobnych (H0 = {K * K / N:.3f})", obs["n_test"],
        {"gain_per_10k": obs["gain"] * 1e4, "null_gain_per_10k": (null * 1e4).tolist(),
         "weights": dict(zip(["wyraz wolny", *FEATURE_NAMES], obs["weights"]))},
    )
