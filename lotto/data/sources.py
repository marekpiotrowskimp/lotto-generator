"""Pobieranie i parsowanie źródeł losowań.

Parsery są czystymi funkcjami (tekst -> dane), żeby dało się je testować bez sieci.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import httpx

from lotto import config
from lotto.data.validate import Draw, InvalidDraw, validate_numbers


def fetch_text(url: str) -> str:
    src = config.load()["sources"]
    headers = {"User-Agent": src["user_agent"]}
    with httpx.Client(timeout=src["timeout"], follow_redirects=True, headers=headers) as c:
        r = c.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" in ctype and not url.endswith("/"):
            raise ValueError(f"{url}: oczekiwano pliku z danymi, otrzymano HTML ({ctype})")
        return r.text


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d.%m.%Y").date()


def parse_wynikilotto_csv(text: str) -> dict[int, tuple[date, tuple[int, ...]]]:
    """Format: `0001,27.01.1957,08,12,31,39,43,45` (liczby w kolejności z pliku)."""
    out: dict[int, tuple[date, tuple[int, ...]]] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 8:
            raise ValueError(f"linia {lineno}: oczekiwano 8 pól, jest {len(parts)}: {line!r}")
        nums = tuple(int(p) for p in parts[2:])
        validate_numbers(nums)
        no = int(parts[0])
        if no in out:
            raise ValueError(f"linia {lineno}: zduplikowany numer losowania {no}")
        out[no] = (_parse_date(parts[1]), nums)
    return out


_MBNET_LINE = re.compile(r"^(\d+)\.\s+(\d{2}\.\d{2}\.\d{4})\s+([\d,]+)$")


def parse_mbnet(text: str) -> dict[int, tuple[date, tuple[int, ...]]]:
    """Format: `1. 27.01.1957 8,12,31,39,43,45`."""
    out: dict[int, tuple[date, tuple[int, ...]]] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        m = _MBNET_LINE.match(line)
        if not m:
            raise ValueError(f"linia {lineno}: nieznany format: {line!r}")
        nums = tuple(sorted(int(x) for x in m[3].split(",")))
        validate_numbers(nums)
        out[int(m[1])] = (_parse_date(m[2]), nums)
    return out


def build_draws(
    sorted_rows: dict,
    order_rows: dict | None,
    order_since: int,
    corrections: dict[int, dict] | None = None,
    warnings: list[str] | None = None,
) -> list[Draw]:
    """Łączy plik posortowany z plikiem w kolejności losowania.

    Kolejność zapisujemy tylko od losowania `order_since`; wcześniej plik
    „niesortowany” zawiera liczby posortowane, więc to nie jest prawdziwa kolejność.
    Różne liczby w plikach to błąd; różna data to ostrzeżenie (do rozstrzygnięcia
    przez `corrections`, czyli jawne poprawki z config.yaml).
    """
    corrections = corrections or {}
    draws = []
    for no, (d, nums) in sorted(sorted_rows.items()):
        nums = tuple(sorted(nums))
        order = None
        if order_rows and no in order_rows:
            od, onums = order_rows[no]
            if tuple(sorted(onums)) != nums:
                raise InvalidDraw(f"losowanie {no}: pliki posortowany i niesortowany mają różne liczby")
            if od != d and "date" not in corrections.get(no, {}) and warnings is not None:
                warnings.append(f"losowanie {no}: różne daty w plikach ({d} / {od})")
            if no >= order_since:
                order = onums
        if "date" in corrections.get(no, {}):
            d = date.fromisoformat(str(corrections[no]["date"]))
        draws.append(Draw(no, d, nums, order))
    return draws


def compare_sources(primary: dict, secondary: dict) -> list[dict]:
    """Różnice między źródłami na wspólnym zakresie numerów losowań."""
    diffs = []
    for no in sorted(primary.keys() & secondary.keys()):
        (d1, n1), (d2, n2) = primary[no], secondary[no]
        n1, n2 = tuple(sorted(n1)), tuple(sorted(n2))
        if d1 != d2 or n1 != n2:
            diffs.append({"draw_no": no, "primary": (d1, n1), "secondary": (d2, n2)})
    return diffs
