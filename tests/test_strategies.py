from datetime import date, timedelta

import numpy as np
import pytest

from lotto.analysis import data as ad
from lotto.analysis import popularity
from lotto.strategies import REGISTRY, get, wheel
from lotto.strategies.advanced import AntiPopularStrategy, DiscoveredStrategy


def synthetic(n=900, seed=0):
    rng = np.random.default_rng(seed)
    X, order = ad.simulate(n, rng)
    dates = np.array([np.datetime64(date(2010, 1, 1) + timedelta(days=2 * i), "D") for i in range(n)])
    return ad.DrawData(np.arange(1, n + 1), dates, X, order)


def synthetic_prizes(d, beta_true, seed=1):
    """Liczba trójek zależna od popularności wylosowanych liczb (+ szum i trend sprzedaży)."""
    rng = np.random.default_rng(seed)
    out = {}
    for i, no in enumerate(d.draw_no):
        pop = beta_true[d.numbers[i] - 1].sum()
        trend = 0.0005 * i
        w3 = int(50000 * np.exp(pop + trend + rng.normal(0, 0.05)))
        w4 = max(1, int(w3 / 18))
        out[int(no)] = {3: (w3, 24.0), 4: (w4, 9e5 / w4), 5: (50, 5000.0), 6: (int(rng.random() < 0.1), 2e6)}
    return out


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_strategy_returns_valid_tickets(name):
    d = synthetic()
    kw = {}
    if name == "anti_popular":
        kw["provider"] = popularity.Provider(prizes=synthetic_prizes(d, np.zeros(49)))
    if name == "discovered":
        kw["report"] = {"hypotheses": []}
    st = REGISTRY[name](**kw)
    t = np.asarray(st.generate(d.head(800), 7, np.random.default_rng(0)))
    assert t.shape == (7, 6)
    s = np.sort(t, 1)
    assert (s >= 1).all() and (s <= 49).all() and (np.diff(s, 1) > 0).all()


def test_popularity_recovers_planted_effect():
    d = synthetic(1500)
    beta = np.zeros(49)
    beta[:31] = 0.06          # „daty” popularne
    beta[[6, 12]] += 0.08     # 7 i 13
    pf = popularity.prize_frame(d, synthetic_prizes(d, beta))
    m = popularity.fit(d, pf)
    assert np.corrcoef(m.beta, beta - beta.mean())[0, 1] > 0.9
    ev = popularity.evaluate(d, pf, date(2010, 1, 1) + timedelta(days=2 * 1000))
    assert ev["corr_combo_test"] > 0.5 and ev["p_corr_combo"] < 0.01


def test_popularity_provider_ignores_future():
    d = synthetic(900)
    prizes = synthetic_prizes(d, np.zeros(49))
    # „przyszłe” wygrane z absurdalną popularnością liczby 1 nie mogą wpłynąć na model z historii do 600
    poisoned = {k: ({**v, 3: (v[3][0] * 50, 24.0)} if k > 600 and 1 in d.numbers[k - 1] else v) for k, v in prizes.items()}
    a = popularity.Provider(prizes=prizes).model(d.head(600))
    b = popularity.Provider(prizes=poisoned).model(d.head(600))
    assert np.allclose(a.beta, b.beta)


def test_anti_popular_avoids_popular_numbers():
    d = synthetic(1200)
    beta = np.zeros(49)
    beta[:31] = 0.1
    st = AntiPopularStrategy(provider=popularity.Provider(prizes=synthetic_prizes(d, beta)), candidates=5000)
    t = st.generate(d.head(1200), 5, np.random.default_rng(0))
    assert (t > 31).mean() > 0.8


def test_discovered_uses_only_train_selected():
    report = {"params": {"alpha": 0.05}, "hypotheses": [
        {"id": "freq.07", "train": {"q": 0.01, "effect": 0.2}},     # wybrana na train
        {"id": "freq.13", "train": {"q": 0.30, "effect": 0.5}},     # niewybrana
        {"id": "ml.logistic", "train": None},
    ]}
    st = DiscoveredStrategy(report=report, pool=6)
    assert [h["id"] for h in st.used] == ["freq.07"]
    t = st.generate(synthetic().head(500), 1, np.random.default_rng(0))
    assert st.weights[6] > 0 and st.weights[12] == 0
    assert 7 in t[0]   # jedyna faworyzowana liczba zawsze trafia do puli
    assert DiscoveredStrategy(report={"hypotheses": []}).weights.sum() == 0


@pytest.mark.parametrize("g", ["3if3", "3if4", "4if4", "4if5", "5if6"])
def test_wheel_guarantee(g):
    pool = [3, 8, 11, 19, 24, 30, 33, 37, 41, 46]
    t, k = wheel.GUARANTEES[g]
    tk = wheel.cover(pool, t, k)
    assert wheel.verify(pool, tk, t, k)
    assert set(np.ravel(tk)) <= set(pool)
    assert len(tk) < wheel.full_system_size(len(pool))


def test_wheel_rejects_bad_input():
    with pytest.raises(ValueError):
        wheel.cover([1, 2, 3, 4, 5], 3, 3)
    with pytest.raises(ValueError):
        wheel.cover(list(range(1, 11)), 4, 3)


def test_generator_next_draw_date():
    from lotto.generator import next_draw_date
    assert next_draw_date(date(2026, 10, 10)) == date(2026, 10, 13)   # sob → wt
    assert next_draw_date(date(2026, 10, 13)) == date(2026, 10, 15)   # wt → czw
    assert next_draw_date(date(2026, 10, 15)) == date(2026, 10, 17)   # czw → sob
