"""Wygrane, liczba zwycięzców i pula dla każdego losowania (strony wynikilotto.net.pl).

Parsery są czystymi funkcjami (HTML -> dane), pobieranie jest osobno.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from lotto import config
from lotto.data import db, sources

MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paz", "lis", "gru"]
TIERS = {"I": 6, "II": 5, "III": 4, "IV": 3}


def slug(d: date) -> str:
    """Adres strony losowania, np. 10.10.2026 -> `10-paz-2026`."""
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def _money(s: str) -> float:
    """`9 345 079,70` / `11 861 121 zł` -> float."""
    s = html.unescape(s).replace("zł", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    return float(s)


@dataclass
class DrawPage:
    draw_no: int
    date: date
    numbers: tuple[int, ...] | None
    total_pool: float | None
    prizes: dict[int, tuple[int, float]] = field(default_factory=dict)  # tier -> (winners, amount)


_DL = re.compile(r"<dt>\s*(.*?)\s*</dt>\s*<dd>\s*(.*?)\s*</dd>", re.S)
_ROW = re.compile(
    r"<tr[^>]*>\s*<td>\s*(I|II|III|IV):\s*\d/6[^<]*</td>\s*<td>\s*(\d+)[^<]*(?:<a[^>]*>.*?</a>)?\s*</td>\s*<td>\s*([\d\s\xa0,]+?)\s*</td>",
    re.S,
)
_NUMBERS = re.compile(r"Wyniki Lotto [\d.]+ to:</strong>\s*([\d,\s]+)\.")


def parse_draw_page(page: str) -> DrawPage:
    info = {html.unescape(k).strip(): html.unescape(re.sub(r"<[^>]+>", " ", v)).strip()
            for k, v in _DL.findall(page)}
    if "Numer losowania" not in info or "Data losowania" not in info:
        raise ValueError("strona bez informacji o losowaniu")
    draw_no = int(info["Numer losowania"])
    d = datetime.strptime(info["Data losowania"], "%d.%m.%Y").date()

    pool = None
    pool_raw = info.get("Całkowita pula PLN", "")
    if re.fullmatch(r"[\d\s\xa0]+(,\d+)?\s*zł", pool_raw):
        pool = _money(pool_raw)

    prizes = {}
    for tier, winners, amount in _ROW.findall(page):
        prizes[TIERS[tier]] = (int(winners), _money(amount))
    if prizes and set(prizes) != {3, 4, 5, 6}:
        raise ValueError(f"losowanie {draw_no}: niepełna tabela wygranych {sorted(prizes)}")

    numbers = None
    m = _NUMBERS.search(page)
    if m:
        numbers = tuple(sorted(int(x) for x in m[1].split(",")))
    return DrawPage(draw_no, d, numbers, pool, prizes)


def parse_current_jackpot(page: str) -> float | None:
    """Zapowiadana pula na szóstkę w najbliższym losowaniu (np. „Kumulacja Lotto 8 000 000 zł”)."""
    text = re.sub(r"<[^>]+>", " ", page)
    m = re.search(r"Kumulacja\s+Lotto\s+([\d\s\xa0]+?)\s*zł", html.unescape(text))
    return _money(m[1]) if m else None


# --- pobieranie ---------------------------------------------------------------

def draws_to_fetch(conn, since: date, retry_recent_days: int = 14) -> list[tuple[int, date]]:
    """Losowania bez wygranych w bazie.

    Pomijamy te, dla których strona nie miała danych (`no_data`), chyba że losowanie
    jest świeże: serwis uzupełnia wygrane z opóźnieniem.
    """
    recent = (date.today() - timedelta(days=retry_recent_days)).isoformat()
    rows = conn.execute(
        """SELECT d.draw_no, d.date FROM draws d
           LEFT JOIN prize_fetch f ON f.draw_no = d.draw_no
           WHERE d.date >= ?
             AND (f.status IS NULL OR f.status = 'error' OR (f.status = 'no_data' AND d.date >= ?))
           ORDER BY d.draw_no""",
        (since.isoformat(), recent),
    ).fetchall()
    return [(r["draw_no"], date.fromisoformat(r["date"])) for r in rows]


def fetch_prizes(
    conn,
    since: date | None = None,
    delay: float | None = None,
    limit: int | None = None,
    progress: Callable[[int, int, int], None] | None = None,
) -> dict:
    """Pobiera brakujące wygrane. Zwraca liczniki ok / no_data / error."""
    cfg = config.load()
    since = since or date.fromisoformat(cfg["data"]["prizes_since"])
    delay = cfg["sources"]["request_delay"] if delay is None else delay
    url = cfg["sources"]["wynikilotto_draw_page"]

    todo = draws_to_fetch(conn, since)
    if limit:
        todo = todo[:limit]
    stats = {"ok": 0, "no_data": 0, "error": 0, "mismatch": 0, "total": len(todo)}
    for i, (no, d) in enumerate(todo, 1):
        status, msg = "ok", ""
        try:
            page = parse_draw_page(sources.fetch_text(url.format(slug=slug(d))))
            expected = db.get_draw(conn, no)
            if page.draw_no != no or page.date != d:
                raise ValueError(f"strona opisuje losowanie {page.draw_no} z {page.date}")
            if page.numbers and page.numbers != expected.numbers:
                stats["mismatch"] += 1
                msg = f"liczby na stronie {page.numbers} != w bazie {expected.numbers}"
            if page.prizes:
                db.save_prizes(conn, no, page.prizes, page.total_pool)
            else:
                status = "no_data"
        except Exception as e:  # pojedyncza strona nie przerywa całej synchronizacji
            status, msg = "error", str(e)[:300]
        db.mark_prize_fetch(conn, no, status, msg)
        stats[status] += 1
        if progress:
            progress(i, len(todo), no)
        if i < len(todo) and delay:
            time.sleep(delay)
    return stats
