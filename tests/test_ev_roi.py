from datetime import date, timedelta

import numpy as np
import pytest

from lotto import ev, roi_sim
from lotto.analysis import data as ad
from lotto.analysis import jackpot as jp
from lotto.backtest import engine


def chain_data():
    """6 losowań: wygrana w 3. (2 zwycięzców po 5 mln), potem 2 bez wygranej."""
    n = 6
    X, order = ad.simulate(n, np.random.default_rng(0))
    dates = np.array([np.datetime64(date(2020, 1, 4) + timedelta(days=3 * i), "D") for i in range(n)])
    d = ad.DrawData(np.arange(100, 100 + n), dates, X, order)
    W3 = [40000, 50000, 60000, 40000, 40000, 80000]
    w6 = [0, 0, 2, 0, 0, 0]
    a6 = [0, 0, 5e6, 0, 0, 0]
    prizes = {100 + i: {3: (W3[i], 24.0), 4: (2000, 180.0), 5: (50, 6000.0), 6: (w6[i], a6[i])} for i in range(n)}
    return d, prizes


def test_jackpot_reconstruction():
    d, prizes = chain_data()
    js = jp.reconstruct(d, prizes, announced_next=6e6)
    assert np.isnan(js.jackpot[:2]).all()                  # przed pierwszą wygraną: nieznane
    assert js.jackpot[2] == 10e6 and js.exact[2]
    # po wygranej: start od minimum 2 mln, rośnie proporcjonalnie do sprzedaży aż do zapowiedzi 6 mln
    assert js.jackpot[3] == pytest.approx(2e6)
    s = js.sales[3:]
    assert js.jackpot[4] == pytest.approx(2e6 + 4e6 * s[0] / s.sum())
    assert js.jackpot[5] == pytest.approx(2e6 + 4e6 * (s[0] + s[1]) / s.sum())
    assert js.sales[0] == pytest.approx(40000 / jp.P3)


def make_evm(**kw):
    base = dict(on=date(2026, 10, 13), price=5.0, prize3=35, prize4=300.0, prize5=10000.0,
                sales_a=np.log(2e6) - 0.35 * np.log(2e6), sales_b=0.35, mult4_anti=2.0, mult5_anti=1.3, n_recent=20)
    return ev.EVModel(**(base | kw))


def test_ev_components_and_break_even():
    m = make_evm()
    r = m.ev(10e6)
    assert r["parts"][3] == pytest.approx(ev.PK[3] * 35)
    assert r["parts"][5] == pytest.approx(ev.PK[5] * 10000 * 0.9)          # podatek powyżej progu
    lam = m.sales(10e6) * ev.PK[6]
    assert r["share"] == pytest.approx((1 - np.exp(-lam)) / lam)
    assert m.ev(20e6)["ev"] > r["ev"]
    assert m.ev(10e6, anti=True)["ev"] > r["ev"]
    be, be_anti = m.break_even(), m.break_even(True)
    assert be_anti < be and m.ev(be)["ev"] == pytest.approx(5.0, rel=1e-6)


def test_lotto_plus_ev():
    lp = make_evm().lotto_plus()
    assert lp["ev"] == pytest.approx(1e6 * 0.9 / 13_983_816)
    assert lp["roi"] < -0.9


def dataset(n=60):
    rng = np.random.default_rng(1)
    X, order = ad.simulate(n, rng)
    dates = np.array([np.datetime64(date(2021, 1, 2) + timedelta(days=2 * i), "D") for i in range(n)])
    d = ad.DrawData(np.arange(1, n + 1), dates, X, order)
    prizes = {i: {3: (50000, 24.0), 4: (3000, 180.0), 5: (60, 6000.0), 6: (0, 0.0)} for i in range(1, n + 1)}
    table, est6 = engine.build_prize_table(d, prizes, {i: 1e6 * i for i in range(1, n + 1)})
    return engine.Dataset(d, table, np.full(n, 3.0), est6, np.array([1e6 * i for i in range(1, n + 1)]))


def test_choose_draws_threshold_and_budget():
    ds = dataset()
    idx = np.arange(len(ds.d))
    assert (ds.jackpot[roi_sim.choose_draws(ds, idx, 1, 30e6, None, False)] >= 30e6).all()
    played = roi_sim.choose_draws(ds, idx, 2, 0, 30, False)          # 6 zł na losowanie, 30 zł na miesiąc
    months = np.array([str(x)[:7] for x in ds.d.dates[played]])
    assert max(np.unique(months, return_counts=True)[1]) == 5
    assert len(roi_sim.choose_draws(ds, idx, 1, 0, 30, True)) < len(roi_sim.choose_draws(ds, idx, 1, 0, 30, False))


def test_simulate_policy(monkeypatch):
    ds = dataset()
    cfg = {**roi_sim.config.load(), "split": {"test_since": "2021-01-01"}}
    monkeypatch.setattr(roi_sim.config, "load", lambda: cfg)
    m = make_evm(price=3.0)
    r = roi_sim.simulate(ds, m, "random", None, 2, 20e6, None, False, "test", sims=50)
    assert r["draws_played"] == len(ds.d) - 19
    assert r["cost"] == pytest.approx(r["draws_played"] * 2 * 3.0)
    assert -1 < r["expected"]["roi"] and r["realized"]["max_drawdown"] >= 0
    hi = roi_sim.simulate(ds, m, "random", None, 1, 50e6, None, False, "test", realized=False)
    lo = roi_sim.simulate(ds, m, "random", None, 1, 0, None, False, "test", realized=False)
    assert hi["expected"]["roi"] > lo["expected"]["roi"]           # wyższa kumulacja → lepsze EV
    none = roi_sim.simulate(ds, m, "random", None, 1, 1e12, None, False, "test")
    assert none["draws_played"] == 0 and none["expected"] is None
