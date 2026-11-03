"""Wczytywanie config.yaml i zapytania o zasady obowiązujące w danym dniu."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def db_path() -> Path:
    return ROOT / load()["data"]["db_path"]


def _active(entries: list[dict], on: date) -> dict | None:
    """Ostatni wpis z listy {since: ...}, który obowiązuje w dniu `on`."""
    current = None
    for e in sorted(entries, key=lambda e: e["since"]):
        if date.fromisoformat(e["since"]) <= on:
            current = e
    return current


def ticket_price(on: date) -> float | None:
    e = _active(load()["ticket_price"], on)
    return e["price"] if e else None


def fixed_prizes(on: date) -> dict | None:
    return _active(load()["fixed_prizes"], on)
