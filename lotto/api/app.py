"""Serwer WWW: REST API + statyczny frontend z katalogu web/.

Start: uvicorn lotto.api.app:app (albo ./run.sh)
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from lotto import config
from lotto.analysis import protocol, validate
from lotto.backtest import engine
from lotto import ev, generator, roi_sim, strategies
from lotto.data import db, sync

app = FastAPI(title="Lotto", docs_url="/api/docs")


class BackgroundJob:
    """Zadanie w tle (synchronizacja, analiza, walidacja); najwyżej jedno naraz danego typu.

    `fn(progress)` wykonuje pracę i zwraca krótki wynik; `progress(phase, done, total)`.
    """

    def __init__(self, first_phase: str):
        self._lock = threading.Lock()
        self.first_phase = first_phase
        self.state = {"running": False, "phase": None, "done": 0, "total": 0,
                      "started_at": None, "finished_at": None, "result": None, "error": None}

    def start(self, fn: Callable[[Callable], dict]) -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self.state.update(running=True, phase=self.first_phase, done=0, total=0, result=None, error=None,
                              started_at=datetime.now().isoformat(timespec="seconds"), finished_at=None)
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()
        return True

    def _progress(self, phase: str, done: int, total: int) -> None:
        self.state.update(phase=phase, done=done, total=total)

    def _run(self, fn) -> None:
        try:
            self.state["result"] = fn(self._progress)
        except Exception as e:
            self.state["error"] = f"{type(e).__name__}: {e}"
        finally:
            self.state.update(running=False, phase=None,
                              finished_at=datetime.now().isoformat(timespec="seconds"))


job = BackgroundJob("losowania")
analysis_job = BackgroundJob("analiza")
validation_job = BackgroundJob("walidacja")


def _sync(with_prizes: bool):
    def run(progress):
        conn = db.connect()
        try:
            return sync.sync_all(conn, with_prizes=with_prizes,
                                 progress=lambda i, n, _no: progress("wygrane", i, n))
        finally:
            conn.close()
    return run


def _analysis(progress):
    r = protocol.run_from_db(progress)
    return {"summary": r["summary"], "generated_at": r["generated_at"], "runtime_s": r["runtime_s"]}


def _validation(progress):
    r = validate.run_from_db(progress=progress)
    return {"generated_at": r["generated_at"]}


def _conn():
    return db.connect()


@app.get("/api/status")
def status():
    conn = _conn()
    try:
        last = db.last_draw(conn)
        jackpot = db.get_state(conn, "next_jackpot")
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        last_sync = conn.execute(
            "SELECT ts, source, added, status, message FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "draws": db.count_draws(conn),
            "first_date": q("SELECT MIN(date) FROM draws"),
            "last_draw": dict(last) if last else None,
            "draws_with_order": q("SELECT COUNT(*) FROM draws WHERE o1 IS NOT NULL"),
            "draws_with_prizes": q("SELECT COUNT(DISTINCT draw_no) FROM prizes"),
            "disputes": q("SELECT COUNT(DISTINCT draw_no) FROM disputes"),
            "next_jackpot": float(jackpot["value"]) if jackpot else None,
            "next_jackpot_updated": jackpot["updated_at"] if jackpot else None,
            "last_sync": dict(last_sync) if last_sync else None,
            "ticket_price": config.ticket_price(datetime.now().date()),
            "sync_job": job.state,
        }
    finally:
        conn.close()


@app.post("/api/sync")
def start_sync(prizes: bool = True):
    started = job.start(_sync(prizes))
    return {"started": started, "job": job.state}


@app.get("/api/sync/status")
def sync_status():
    return job.state


@app.get("/api/draws")
def draws(limit: int = Query(20, ge=1, le=500), offset: int = Query(0, ge=0)):
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT d.*, m.total_pool,
                      (SELECT COUNT(*) FROM disputes x WHERE x.draw_no = d.draw_no) AS disputed
               FROM draws d LEFT JOIN draw_meta m ON m.draw_no = d.draw_no
               ORDER BY d.draw_no DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        prizes: dict[int, dict] = {}
        if rows:
            nos = [r["draw_no"] for r in rows]
            for p in conn.execute(
                f"SELECT * FROM prizes WHERE draw_no IN ({','.join('?' * len(nos))})", nos):
                prizes.setdefault(p["draw_no"], {})[p["tier"]] = {"winners": p["winners"], "amount": p["amount"]}
        out = []
        for r in rows:
            order = [r[f"o{i}"] for i in range(1, 7)]
            out.append({
                "draw_no": r["draw_no"], "date": r["date"],
                "numbers": [r[f"n{i}"] for i in range(1, 7)],
                "order": order if order[0] is not None else None,
                "total_pool": r["total_pool"], "prizes": prizes.get(r["draw_no"]),
                "disputed": bool(r["disputed"]),
            })
        return out
    finally:
        conn.close()


@app.get("/api/analysis")
def analysis_report():
    r = protocol.load_report()
    if r is None:
        raise HTTPException(404, "Brak raportu. Uruchom analizę.")
    return {**r, "job": analysis_job.state}


@app.post("/api/analysis/run")
def analysis_run():
    return {"started": analysis_job.start(_analysis), "job": analysis_job.state}


@app.get("/api/analysis/status")
def analysis_status():
    return {"analysis": analysis_job.state, "validation": validation_job.state}


@app.get("/api/validation")
def validation_report():
    r = validate.load_report()
    if r is None:
        raise HTTPException(404, "Brak raportu walidacji.")
    return r


@app.post("/api/validation/run")
def validation_run():
    return {"started": validation_job.start(_validation), "job": validation_job.state}


_dataset: dict = {}


def dataset() -> engine.Dataset:
    """Dane do backtestu, przeładowywane po synchronizacji (zmiana liczby losowań lub wygranych)."""
    conn = db.connect()
    try:
        key = conn.execute("SELECT (SELECT COUNT(*) FROM draws), (SELECT COUNT(*) FROM prizes)").fetchone()
    finally:
        conn.close()
    key = tuple(key)
    if _dataset.get("key") != key:
        _dataset.update(key=key, ds=engine.load_dataset())
    return _dataset["ds"]


@app.get("/api/strategies")
def list_strategies():
    return [cls.describe() for cls in strategies.REGISTRY.values()]


class BacktestRequest(BaseModel):
    strategy: str = "random"
    params: dict = Field(default_factory=dict)
    tickets: int = Field(1, ge=1, le=50)
    period: str = Field("test", pattern="^(train|test)$")
    sims: int = Field(500, ge=50, le=5000)
    seed: int = 1


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    try:
        return engine.run(dataset(), req.strategy, req.params, req.tickets, req.period, req.sims, req.seed)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/backtest/compare")
def backtest_compare(tickets: int = Query(5, ge=1, le=50), period: str = Query("test", pattern="^(train|test)$"),
                     sims: int = Query(300, ge=50, le=2000)):
    """Wszystkie strategie z domyślnymi parametrami; skrót wyników."""
    ds = dataset()
    out = []
    for name in strategies.REGISTRY:
        r = engine.run(ds, name, {}, tickets, period, sims)
        out.append({k: r[k] for k in ("strategy", "mean_hits", "mean_hits_ci", "p_mean_hits", "wins_ge3",
                                       "wins_ge3_ci", "p_wins_ge3", "tiers", "money", "beats_random", "draws",
                                       "tickets_per_draw", "range", "period", "alpha")})
    m = len(out)
    for r in out:   # korekta Bonferroniego na liczbę porównywanych strategii
        r["p_mean_hits_bonf"] = min(1.0, r["p_mean_hits"] * m)
        r["beats_random_corrected"] = r["p_mean_hits_bonf"] <= r["alpha"]
    return out


class GenerateRequest(BaseModel):
    strategy: str = "anti_popular"
    params: dict = Field(default_factory=dict)
    tickets: int = Field(5, ge=1, le=100)
    seed: int | None = None
    guarantee: str | None = None
    wheel_pool: int | None = Field(None, ge=6, le=18)
    pool: list[int] | None = None


@app.post("/api/generate")
def generate(req: GenerateRequest):
    try:
        return generator.generate(req.strategy, req.params, req.tickets, req.seed,
                                  req.wheel_pool, req.guarantee, req.pool)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/wheel/guarantees")
def wheel_guarantees():
    from lotto.strategies import wheel
    return [{"id": g, "t": t, "k": k, "label": f"{t} trafienia, jeśli {k} wylosowane są w puli"}
            for g, (t, k) in wheel.GUARANTEES.items()]


@app.get("/api/ev")
def expected_value():
    return ev.summary()


@app.get("/api/roi/grid")
def roi_grid(period: str = Query("all", pattern="^(test|all)$"), tickets: int = Query(1, ge=1, le=50)):
    return roi_sim.policy_grid(dataset(), ev.model(), period, tickets)


class RoiRequest(BaseModel):
    strategy: str = "anti_popular"
    params: dict = Field(default_factory=dict)
    tickets: int = Field(5, ge=1, le=50)
    min_jackpot: float = Field(0, ge=0)
    monthly_budget: float | None = Field(None, gt=0)
    lotto_plus: bool = False
    period: str = Field("all", pattern="^(test|all)$")
    sims: int = Field(300, ge=50, le=2000)
    seed: int = 1


@app.post("/api/roi")
def roi(req: RoiRequest):
    try:
        return roi_sim.simulate(dataset(), ev.model(), req.strategy, req.params, req.tickets, req.min_jackpot,
                                req.monthly_budget, req.lotto_plus, req.period, req.sims, req.seed)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/disputes")
def disputes():
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT x.draw_no, x.source, x.date AS other_date, x.numbers AS other_numbers,
                      d.date, d.n1, d.n2, d.n3, d.n4, d.n5, d.n6
               FROM disputes x JOIN draws d ON d.draw_no = x.draw_no ORDER BY x.draw_no""").fetchall()
        return [{
            "draw_no": r["draw_no"], "date": r["date"],
            "numbers": [r[f"n{i}"] for i in range(1, 7)],
            "other_source": r["source"], "other_date": r["other_date"],
            "other_numbers": [int(x) for x in r["other_numbers"].split(",")],
        } for r in rows]
    finally:
        conn.close()


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(config.ROOT / "web" / "favicon.svg", media_type="image/svg+xml")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/index.html")


app.mount("/", StaticFiles(directory=config.ROOT / "web"), name="web")
