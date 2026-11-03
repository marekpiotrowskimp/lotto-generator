"""Wartość oczekiwana (EV) zakładu w zależności od kumulacji.

EV = P(3)·W3 + P(4)·E[W4] + P(5)·E[W5] + P(6)·E[udział w puli]

- W3: stała wygrana z config.yaml; E[W4], E[W5]: mediana z ostatnich losowań przy obecnych zasadach,
  netto po podatku;
- udział w puli J: pozostali zwycięzcy ~ Poisson(λ), λ = sprzedaż(J)·P(6), więc
  E[1/(1+X)] = (1 − e^(−λ))/λ; sprzedaż rośnie z kumulacją (model z danych);
- strategia „niepopularne”: wygrane za 4 i 5 × mnożnik z modelu popularności,
  λ / mnożnik(5) dla szóstki (ostrożnie: przy szóstce efekt jest zwykle silniejszy).

Lotto Plus: 1 zł, tylko szóstka, 1 mln zł brutto (stała).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
from scipy import optimize, stats

from lotto import config
from lotto.analysis import jackpot as jp
from lotto.analysis import popularity
from lotto.analysis.data import K, N, from_draws

PK = stats.hypergeom(N, K, K).pmf(np.arange(K + 1))


def net(v: float) -> float:
    tax = config.load()["tax"]
    return v * (1 - tax["rate"]) if v > tax["threshold"] else v


@dataclass
class EVModel:
    on: date
    price: float
    prize3: float
    prize4: float          # mediana brutto
    prize5: float
    sales_a: float
    sales_b: float
    mult4_anti: float
    mult5_anti: float
    n_recent: int

    def sales(self, J: float) -> float:
        return float(np.exp(self.sales_a) * J ** self.sales_b)

    def ev(self, J: float, anti: bool = False) -> dict:
        m4 = self.mult4_anti if anti else 1.0
        m5 = self.mult5_anti if anti else 1.0
        lam = self.sales(J) * PK[6] / m5
        share = (1 - np.exp(-lam)) / lam if lam > 0 else 1.0
        parts = {
            3: PK[3] * net(self.prize3),
            4: PK[4] * net(self.prize4 * m4),
            5: PK[5] * net(self.prize5 * m5),
            6: PK[6] * net(J * share),
        }
        total = sum(parts.values())
        return {"jackpot": J, "ev": total, "parts": parts, "roi": total / self.price - 1,
                "expected_other_winners": lam, "share": share}

    def break_even(self, anti: bool = False) -> float | None:
        f = lambda J: self.ev(J, anti)["ev"] - self.price  # noqa: E731
        hi = 1e9
        if f(hi) < 0:
            return None
        return float(optimize.brentq(f, 1e6, hi))

    def lotto_plus(self) -> dict:
        lp = config.load()["lotto_plus"]
        ev = PK[6] * net(lp["prize_6"])
        return {"price": lp["price"], "ev": ev, "roi": ev / lp["price"] - 1}


@lru_cache(maxsize=4)
def _build(n_draws: int, n_prizes: int, announced: float | None) -> tuple:
    from lotto import generator
    from lotto.data import db
    conn = db.connect()
    try:
        d = from_draws(db.load_draws(conn))
    finally:
        conn.close()
    prizes = popularity._db_prizes()
    js = jp.reconstruct(d, prizes, announced)
    a, b = jp.sales_model(js)
    # anty-popularność: mnożniki dla zakładów z generatora (wynik przycięty do obserwowanego zakresu)
    _, model, ev, ref = generator.context()
    lo = ev["score_range"][0]
    m4 = float(np.exp(ev["slope_log_prize4"] * (lo - ref.mean())))
    m5 = float(np.exp(ev["slope_log_prize5"] * (lo - ref.mean())))
    return d, prizes, js, a, b, m4, m5


def model(on: date | None = None) -> EVModel:
    from lotto.data import db
    conn = db.connect()
    try:
        n_d, n_p = conn.execute("SELECT (SELECT COUNT(*) FROM draws), (SELECT COUNT(*) FROM prizes)").fetchone()
        st = db.get_state(conn, "next_jackpot")
    finally:
        conn.close()
    announced = float(st["value"]) if st else None
    d, prizes, js, a, b, m4, m5 = _build(n_d, n_p, announced)
    on = on or date.today()
    rules = config.fixed_prizes(on) or {}
    since = np.datetime64(rules.get("since", "1900-01-01"), "D")
    recent = [int(no) for no, dt in zip(d.draw_no, d.dates) if dt >= since and int(no) in prizes]
    if len(recent) < 8:                       # za mało losowań po zmianie zasad: ostatnie 60
        recent = [int(no) for no in d.draw_no[-60:] if int(no) in prizes]
    p4 = float(np.median([prizes[no][4][1] for no in recent]))
    p5 = float(np.median([prizes[no][5][1] for no in recent]))
    return EVModel(on, config.ticket_price(on), rules.get("prize_3", 24), p4, p5, a, b, m4, m5, len(recent))


def jackpot_series():
    """Odtworzona kumulacja (dla symulatora ROI)."""
    m = model()
    from lotto.data import db
    conn = db.connect()
    try:
        n_d, n_p = conn.execute("SELECT (SELECT COUNT(*) FROM draws), (SELECT COUNT(*) FROM prizes)").fetchone()
        st = db.get_state(conn, "next_jackpot")
    finally:
        conn.close()
    return _build(n_d, n_p, float(st["value"]) if st else None)[2], m


def summary() -> dict:
    m = model()
    js, _ = jackpot_series()
    grid = np.unique(np.r_[np.linspace(2e6, 20e6, 19), np.linspace(25e6, 150e6, 26)])
    curve = [{"jackpot": float(J), "ev": m.ev(J)["ev"], "ev_anti": m.ev(J, True)["ev"]} for J in grid]
    nxt = js.next_jackpot
    ok = np.isfinite(js.jackpot)
    return {
        "date": str(m.on), "price": m.price, "prize3": m.prize3, "prize4_median": m.prize4,
        "prize5_median": m.prize5, "recent_draws": m.n_recent,
        "sales_model": {"a": m.sales_a, "b": m.sales_b, "at_2m": m.sales(2e6), "at_50m": m.sales(5e7)},
        "anti_multipliers": {"prize4": m.mult4_anti, "prize5": m.mult5_anti},
        "break_even": {"random": m.break_even(False), "anti_popular": m.break_even(True)},
        "next": {"jackpot": nxt, "random": m.ev(nxt) if nxt else None, "anti_popular": m.ev(nxt, True) if nxt else None},
        "lotto_plus": m.lotto_plus(),
        "curve": curve,
        "history": {"max_jackpot": float(np.nanmax(js.jackpot)) if ok.any() else None,
                    "share_above_break_even": float((js.jackpot[ok] >= (m.break_even(True) or np.inf)).mean())
                    if ok.any() else None,
                    "quantiles": {q: float(np.quantile(js.jackpot[ok], q)) for q in (0.5, 0.9, 0.99)} if ok.any() else None},
    }
