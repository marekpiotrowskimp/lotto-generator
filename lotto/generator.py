"""Generator kuponów na najbliższe losowanie: strategia (+ opcjonalne pokrycie puli),
koszt, popularność zakładów i szacowany mnożnik wygranej za 4–5 przy trafieniu."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from lotto import config
from lotto.analysis import popularity
from lotto.analysis.data import from_draws
from lotto.strategies import base as sb
from lotto.strategies import wheel

DRAW_WEEKDAYS = {1, 3, 5}   # wt, czw, sob


def next_draw_date(after: date) -> date:
    d = after + timedelta(days=1)
    while d.weekday() not in DRAW_WEEKDAYS:
        d += timedelta(days=1)
    return d


@lru_cache(maxsize=4)
def _context(n_draws: int, n_prizes: int):
    """Dane i model popularności (przeliczane po synchronizacji)."""
    from lotto.data import db
    popularity.clear_cache()
    conn = db.connect()
    try:
        d = from_draws(db.load_draws(conn))
    finally:
        conn.close()
    prizes = popularity._db_prizes()
    pf = popularity.prize_frame(d, prizes)
    model = popularity.fit(d, pf)
    ev = popularity.evaluate(d, pf, date.fromisoformat(config.load()["split"]["test_since"]))
    rng = np.random.default_rng(0)
    ref = model.score(sb.random_tickets(50_000, rng), d.numbers[-1])
    return d, model, ev, np.sort(ref)


def context():
    from lotto.data import db
    conn = db.connect()
    try:
        n_d, n_p = conn.execute("SELECT (SELECT COUNT(*) FROM draws), (SELECT COUNT(*) FROM prizes)").fetchone()
    finally:
        conn.close()
    return _context(n_d, n_p)


def generate(strategy: str, params: dict | None = None, tickets: int = 5, seed: int | None = None,
             wheel_pool: int | None = None, guarantee: str | None = None, pool: list[int] | None = None) -> dict:
    d, model, ev, ref = context()
    rng = np.random.default_rng(seed)
    st = sb.get(strategy, **(params or {}))
    used_pool = None
    if guarantee:
        if guarantee not in wheel.GUARANTEES:
            raise ValueError(f"nieznana gwarancja: {guarantee}")
        if pool:
            used_pool = sorted(set(int(x) for x in pool))
            if any(not 1 <= x <= 49 for x in used_pool):
                raise ValueError("liczby puli muszą być z zakresu 1–49")
        else:
            m = int(wheel_pool or 10)
            # pula: liczby najczęściej wybierane przez strategię w wielu zakładach
            many = st.generate(d, 60, rng)
            counts = np.bincount(np.asarray(many).ravel(), minlength=50)[1:] + rng.random(49) * 1e-3
            used_pool = sorted((np.argsort(-counts)[:m] + 1).tolist())
        t, k = wheel.GUARANTEES[guarantee]
        tk = wheel.cover(used_pool, t, k, rng)
        if not wheel.verify(used_pool, tk, t, k):
            raise RuntimeError("pokrycie nie spełnia gwarancji")
    else:
        tk = np.asarray(st.generate(d, tickets, rng))
    tk = np.sort(tk, axis=1)

    last_date = d.dates[-1].astype(object)
    draw_day = next_draw_date(max(last_date, date.today() - timedelta(days=1)))
    price = config.ticket_price(draw_day)
    score = model.score(tk, d.numbers[-1])
    # odsetek wszystkich kombinacji typowanych częściej niż dany zakład
    rarer_than = 1 - np.searchsorted(ref, score) / len(ref)
    mean_ref = float(ref.mean())
    # mnożnik wygranej względem przeciętnego zakładu; wynik przycinamy do zakresu
    # obserwowanego w losowaniach (ostrożnie: bez ekstrapolacji poza dane)
    clipped = np.clip(score, *ev["score_range"])
    mult4 = np.exp(ev["slope_log_prize4"] * (clipped - mean_ref))
    mult5 = np.exp(ev["slope_log_prize5"] * (clipped - mean_ref))
    return {
        "strategy": st.describe() | {"values": st.p},
        "draw_date": str(draw_day), "last_draw_no": int(d.draw_no[-1]),
        "price": price, "cost": price * len(tk) if price else None,
        "pool": used_pool, "guarantee": guarantee,
        "full_system_size": wheel.full_system_size(len(used_pool)) if used_pool else None,
        "tickets": [{"numbers": t.tolist(), "rarer_than": float(p), "prize_mult4": float(m4),
                     "prize_mult5": float(m5)} for t, p, m4, m5 in zip(tk, rarer_than, mult4, mult5)],
        "popularity_model": {k: ev[k] for k in ("corr_combo_test", "p_corr_combo", "prize4_unpopular",
                                                "prize4_popular", "prize5_unpopular", "prize5_popular",
                                                "n_train", "n_test")},
        "number_popularity": model.beta.tolist(),
    }
