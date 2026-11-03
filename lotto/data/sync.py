"""Synchronizacja losowań ze źródeł do SQLite.

Użycie:
    python -m lotto.data.sync              # pobierz brakujące losowania
    python -m lotto.data.sync --if-empty   # tylko gdy baza jest pusta (start aplikacji)
    python -m lotto.data.sync --cross-check  # porównaj z archiwum mbnet i zapisz rozbieżności
    python -m lotto.data.sync --prizes     # pobierz też wygrane (pierwszy raz ~1 950 stron, ~35 min)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from lotto import config
from lotto.data import db, prizes, sources
from lotto.data.validate import validate_sequence

SOURCE = "wynikilotto.net.pl"


def sync(conn: sqlite3.Connection) -> dict:
    cfg = config.load()
    src = cfg["sources"]
    try:
        sorted_rows = sources.parse_wynikilotto_csv(sources.fetch_text(src["wynikilotto_sorted"]))
        order_rows = sources.parse_wynikilotto_csv(sources.fetch_text(src["wynikilotto_order"]))
        warnings: list[str] = []
        draws = sources.build_draws(sorted_rows, order_rows, cfg["data"]["draw_order_since"],
                                    cfg.get("corrections") or {}, warnings)
        for w in warnings:
            db.log_sync(conn, SOURCE, 0, "warning", w)
        issues = validate_sequence(draws)
        if issues:
            raise ValueError("; ".join(issues))
        added = db.upsert_draws(conn, draws, SOURCE)
    except Exception as e:
        db.log_sync(conn, SOURCE, 0, "error", str(e))
        raise
    last = db.last_draw(conn)
    db.log_sync(conn, SOURCE, added, "ok", f"ostatnie losowanie {last['draw_no']} z {last['date']}")
    return {"added": added, "total": db.count_draws(conn), "warnings": warnings,
            "last_draw_no": last["draw_no"], "last_date": last["date"]}


def fetch_jackpot(conn: sqlite3.Connection) -> float | None:
    """Zapowiadana kumulacja na najbliższe losowanie (ze strony wyników)."""
    amount = prizes.parse_current_jackpot(sources.fetch_text(config.load()["sources"]["wynikilotto_results"]))
    if amount is not None:
        db.set_state(conn, "next_jackpot", str(amount))
    return amount


def sync_all(conn: sqlite3.Connection, with_prizes: bool = True, progress=None) -> dict:
    """Pełna synchronizacja: losowania, kumulacja, brakujące wygrane."""
    r = sync(conn)
    try:
        r["next_jackpot"] = fetch_jackpot(conn)
    except Exception as e:
        db.log_sync(conn, "kumulacja", 0, "error", str(e))
        r["next_jackpot"] = None
    if with_prizes:
        stats = prizes.fetch_prizes(conn, progress=progress)
        db.log_sync(conn, "wygrane", stats["ok"], "ok" if not stats["error"] else "warning",
                    ", ".join(f"{k}: {v}" for k, v in stats.items()))
        r["prizes"] = stats
    return r


def cross_check(conn: sqlite3.Connection) -> list[dict]:
    """Porównuje bazę z archiwum mbnet; rozbieżności trafiają do tabeli disputes."""
    src = config.load()["sources"]
    mbnet = sources.parse_mbnet(sources.fetch_text(src["mbnet_archive"]))
    ours = {d.draw_no: (d.date, d.numbers) for d in db.load_draws(conn)}
    diffs = sources.compare_sources(ours, mbnet)
    db.record_disputes(conn, diffs, "mbnet.com.pl (archiwum)")
    db.log_sync(conn, "mbnet.com.pl (archiwum)", 0, "ok",
                f"porównano {len(ours.keys() & mbnet.keys())} losowań, rozbieżności: {len(diffs)}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if-empty", action="store_true", help="synchronizuj tylko, gdy baza jest pusta")
    p.add_argument("--cross-check", action="store_true", help="porównaj z archiwum mbnet")
    p.add_argument("--prizes", action="store_true", help="pobierz brakujące wygrane i kumulację")
    p.add_argument("--limit", type=int, help="maksymalna liczba stron wygranych w tym przebiegu")
    args = p.parse_args(argv)

    conn = db.connect()
    if args.if_empty and db.count_draws(conn) > 0:
        last = db.last_draw(conn)
        print(f"Baza zawiera {db.count_draws(conn)} losowań (ostatnie {last['draw_no']} z {last['date']}).")
        return 0

    r = sync(conn)
    print(f"Dodano {r['added']} losowań. W bazie: {r['total']}, ostatnie {r['last_draw_no']} z {r['last_date']}.")
    for w in r["warnings"]:
        print(f"  ostrzeżenie: {w}")

    if args.prizes:
        jackpot = fetch_jackpot(conn)
        print(f"Zapowiadana kumulacja: {jackpot:,.0f} zł" if jackpot else "Nie znaleziono kumulacji.")

        def progress(i, n, no):
            if i % 50 == 0 or i == n:
                print(f"  wygrane: {i}/{n} (losowanie {no})", flush=True)

        stats = prizes.fetch_prizes(conn, limit=args.limit, progress=progress)
        db.log_sync(conn, "wygrane", stats["ok"], "ok" if not stats["error"] else "warning",
                    ", ".join(f"{k}: {v}" for k, v in stats.items()))
        print(f"Wygrane: {stats}")

    if args.cross_check or args.if_empty:
        try:
            diffs = cross_check(conn)
        except Exception as e:  # źródło kontrolne jest opcjonalne
            print(f"Porównanie z archiwum mbnet nieudane: {e}", file=sys.stderr)
        else:
            print(f"Rozbieżności z archiwum mbnet: {len(diffs)}")
            for x in diffs:
                print(f"  {x['draw_no']}: {x['primary'][0]} {x['primary'][1]}  vs  {x['secondary'][0]} {x['secondary'][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
