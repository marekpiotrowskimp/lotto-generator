from datetime import date, timedelta

import numpy as np
import pytest

from lotto.analysis import data as ad
from lotto.backtest import engine
from lotto.strategies import base as sb


def make_dataset(n: int = 700, seed: int = 0) -> engine.Dataset:
    rng = np.random.default_rng(seed)
    X, order = ad.simulate(n, rng)
    dates = np.array([np.datetime64(date(2020, 1, 1) + timedelta(days=2 * i), "D") for i in range(n)])
    d = ad.DrawData(np.arange(1, n + 1), dates, X, order)
    prizes = {int(no): {3: (50000, 24.0), 4: (3000, 180.0), 5: (60, 6000.0), 6: (0, 0.0)} for no in d.draw_no}
    table, est6 = engine.build_prize_table(d, prizes)
    return engine.Dataset(d, table, np.full(n, 3.0), est6)


class Spy(sb.Strategy):
    name, label, description = "spy", "spy", "test"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lengths = []

    def generate(self, history, n, rng):
        self.lengths.append(len(history))
        assert not history.X.flags.writeable
        return sb.random_tickets(n, rng)


class Oracle(sb.Strategy):
    """Zna przyszłość: typuje dokładnie wylosowane liczby (sprawdza, że test wykrywa przewagę)."""
    name, label, description = "oracle", "oracle", "test"
    future: ad.DrawData = None

    def generate(self, history, n, rng):
        nxt = self.future.numbers[len(history)]
        return np.repeat(nxt[None], n, axis=0)


def test_walk_forward_sees_only_past():
    ds = make_dataset()
    idx = np.arange(500, 520)
    spy = Spy()
    engine.walk_forward(ds, spy, idx, 2, np.random.default_rng(0))
    assert spy.lengths == list(idx)


def test_walk_forward_rejects_invalid_tickets():
    class Bad(sb.Strategy):
        name, label, description = "bad", "bad", "x"

        def generate(self, history, n, rng):
            return np.array([[1, 1, 2, 3, 4, 5]] * n)
    with pytest.raises(ValueError, match="niepoprawny"):
        engine.walk_forward(make_dataset(), Bad(), np.arange(300, 302), 1, np.random.default_rng(0))


def test_prize_table():
    ds = make_dataset(10)
    row = ds.prize_table[0]
    assert row[3] == 24.0
    assert row[4] == pytest.approx(180 * 3000 / 3001)
    assert row[5] == pytest.approx(6000 * 60 / 61 * 0.9)          # powyżej progu podatku
    assert row[6] == pytest.approx(2_000_000 * 0.9) and ds.estimated6[0]   # brak zwycięzcy → gwarantowana pula
    assert np.isnan(engine.build_prize_table(ds.d, {})[0]).all()


def test_random_within_h0():
    ds = make_dataset()
    idx = np.arange(300, 700)
    t = engine.walk_forward(ds, sb.get("random"), idx, 5, np.random.default_rng(1))
    r = engine.evaluate(ds, idx, t, 200, 1)
    assert r["mean_hits_ci"][0] <= r["mean_hits"] <= r["mean_hits_ci"][1]
    assert r["p_mean_hits"] > 0.01
    assert r["money"]["cost"] == pytest.approx(400 * 5 * 3.0)


def test_oracle_beats_random():
    ds = make_dataset()
    Oracle.future = ds.d
    idx = np.arange(300, 340)
    t = engine.walk_forward(ds, Oracle(), idx, 1, np.random.default_rng(0))
    r = engine.evaluate(ds, idx, t, 100, 1)
    assert r["mean_hits"] == 6 and r["p_mean_hits"] < 0.02
    assert r["money"]["roi"] > 100


def test_tickets_from_pool_distinct():
    rng = np.random.default_rng(0)
    t = sb.tickets_from_pool(np.arange(1, 13), 10, rng)
    assert t.shape == (10, 6) and len({tuple(x) for x in t}) == 10
    assert t[0].tolist() == [1, 2, 3, 4, 5, 6]
    assert sb.tickets_from_pool(np.arange(1, 7), 3, rng).shape == (3, 6)   # tylko 1 kombinacja → powtórki


def test_strategy_params_validated():
    with pytest.raises(ValueError):
        sb.get("hot", window=1)
    with pytest.raises(ValueError):
        sb.get("hot", nope=3)
    assert sb.get("hot", window="50").p["window"] == 50


def test_api_backtest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lotto.api import app as appmod
    ds = make_dataset()
    monkeypatch.setattr(appmod, "dataset", lambda: ds)
    cfg = {**engine.config.load(), "split": {"test_since": "2023-01-01"}}   # syntetyczne daty: 2020–2023
    monkeypatch.setattr(engine.config, "load", lambda: cfg)
    client = TestClient(appmod.app)
    names = {s["name"] for s in client.get("/api/strategies").json()}
    assert {"random", "hot", "cold"} <= names
    r = client.post("/api/backtest", json={"strategy": "hot", "tickets": 2, "sims": 50}).json()
    assert r["tickets_per_draw"] == 2 and "curve" in r and r["period"] == "test"
    assert client.post("/api/backtest", json={"strategy": "nope"}).status_code == 400
