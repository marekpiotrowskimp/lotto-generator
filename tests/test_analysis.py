from datetime import date, timedelta

import numpy as np
import pytest

from lotto.analysis import data as ad
from lotto.analysis import detectors as dt
from lotto.analysis import ml, protocol, validate
from lotto.data.validate import Draw


def synthetic(n: int, seed: int, weights=None, with_order=True) -> ad.DrawData:
    rng = np.random.default_rng(seed)
    X, order = ad.simulate(n, rng, weights)
    dates = np.array([np.datetime64(date(2000, 1, 1) + timedelta(days=3 * i), "D") for i in range(n)])
    if not with_order:
        order[:] = -1
    return ad.DrawData(np.arange(1, n + 1), dates, X, order)


TEST_SINCE = date(2000, 1, 1) + timedelta(days=3 * 1200)   # 1200 train / reszta test


def test_simulate_is_valid_and_uniform():
    X, order = ad.simulate(20000, np.random.default_rng(0))
    assert (X.sum(1) == 6).all()
    assert (np.sort(order, 1) == np.sort(np.argsort(~X, 1, kind="stable")[:, :6] + 1, 1)).all()
    freq = X.mean(0)
    assert np.abs(freq - 6 / 49).max() < 0.01
    # kolejność: każda pozycja jednostajna
    assert np.abs(np.bincount(order[:, 0], minlength=50)[1:] / 20000 - 1 / 49).max() < 0.01


def test_simulate_weights_bias():
    w = np.ones(49)
    w[6] = 2.0
    X, _ = ad.simulate(20000, np.random.default_rng(0), w)
    assert X[:, 6].mean() > 1.6 * 6 / 49


def test_from_draws_roundtrip():
    draws = [Draw(1, date(2000, 1, 1), (1, 2, 3, 4, 5, 6), (6, 5, 4, 3, 2, 1)),
             Draw(2, date(2000, 1, 4), (10, 20, 30, 40, 45, 49))]
    d = ad.from_draws(draws)
    assert d.numbers.tolist() == [[1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 45, 49]]
    assert d.has_order.tolist() == [True, False]


def test_bh():
    # ręcznie: p·m/rank = 0.04, 0.06, 0.0533, 0.5; minimum kumulatywne od końca → 0.04, 0.0533, 0.0533, 0.5
    assert np.allclose(protocol.bh(np.array([0.01, 0.03, 0.04, 0.5])), [0.04, 0.05333, 0.05333, 0.5], atol=1e-4)
    assert (protocol.bh(np.array([0.2, 0.9])) <= 1).all()
    # kolejność wejścia nie ma znaczenia
    assert np.allclose(protocol.bh(np.array([0.5, 0.04, 0.01, 0.03])), [0.5, 0.05333, 0.04, 0.05333], atol=1e-4)


def test_detectors_calibrated_under_h0():
    """Przy H0 wartości p z analitycznych detektorów są w przybliżeniu jednostajne."""
    ps = []
    for seed in range(6):
        d = synthetic(1500, seed)
        ps += [r.p for f in dt.ANALYTIC for r in f(d)]
    ps = np.array(ps)
    assert 0.02 < (ps <= 0.05).mean() < 0.09
    assert 0.40 < ps.mean() < 0.60


def test_frequency_detects_strong_bias():
    w = np.ones(49)
    w[6] = 1.6
    rs = {r.id: r for r in dt.frequency(synthetic(3000, 1, w))}
    assert rs["freq.07"].p < 1e-6 and rs["freq.07"].effect > 0.3
    assert rs["freq.all"].p < 1e-3


def test_lag_detects_repeats():
    d = validate.repeating(synthetic(3000, 2), np.random.default_rng(3), 0.4)
    rs = {r.id: r for r in dt.lag_overlap(d)}
    assert rs["lag.01"].p < 1e-6 and rs["lag.01"].effect > 0


def test_ball_order_needs_order_data():
    assert dt.ball_order(synthetic(500, 3, with_order=False)) == []
    assert len(dt.ball_order(synthetic(500, 3))) == 7


def test_mc_statistics_keys():
    assert set(dt.mc_statistics(synthetic(400, 4))) == set(dt.MONTE_CARLO)


def test_ml_predictability_runs():
    d = synthetic(900, 5)
    r = ml.predictability(d, np.arange(len(d)) < 600, 5, np.random.default_rng(0))
    assert 0 < r.p <= 1 and len(r.extra["null_gain_per_10k"]) == 5


def test_protocol_h0_and_bias():
    r = protocol.run(synthetic(1600, 6), TEST_SINCE, sims=20, perms=3, alpha=0.05)
    assert r["data"]["n_train"] == 1200 and r["data"]["n_test"] == 400
    assert r["summary"]["n_confirmed"] == 0
    w = np.ones(49)
    w[10] = 2.0
    r = protocol.run(synthetic(1600, 7, w), TEST_SINCE, sims=20, perms=3, alpha=0.05)
    ver = {h["id"]: h["verdict"] for h in r["hypotheses"]}
    assert ver["freq.11"] == "confirmed" and r["summary"]["h0_rejected"]


def test_power_table_monotonic():
    small = protocol.power_table(1000, 200, 140, 0.05)
    big = protocol.power_table(10000, 2000, 140, 0.05)
    for a, b in zip(small, big):
        assert b["min_effect"] < a["min_effect"]


def test_api_analysis_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lotto import config
    from lotto.api.app import app
    cfg = dict(config.load())
    cfg["analysis"] = {**cfg["analysis"], "report_path": str(tmp_path / "r.json")}
    monkeypatch.setattr(config, "load", lambda: cfg)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    client = TestClient(app)
    assert client.get("/api/analysis").status_code == 404
    assert client.get("/api/analysis/status").json()["analysis"]["running"] is False
