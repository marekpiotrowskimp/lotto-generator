"""Walidacja losowań. Wszystkie źródła traktujemy jako niezaufane."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

POOL = 49
PICK = 6
FIRST_DRAW = date(1957, 1, 27)


@dataclass(frozen=True)
class Draw:
    draw_no: int
    date: date
    numbers: tuple[int, ...]            # posortowane rosnąco
    order: tuple[int, ...] | None = None  # kolejność wypadania kul, jeśli znana

    def __post_init__(self):
        validate_draw(self)


class InvalidDraw(ValueError):
    pass


def validate_numbers(nums: tuple[int, ...]) -> None:
    if len(nums) != PICK:
        raise InvalidDraw(f"oczekiwano {PICK} liczb, jest {len(nums)}: {nums}")
    if len(set(nums)) != PICK:
        raise InvalidDraw(f"liczby się powtarzają: {nums}")
    if any(not isinstance(n, int) or n < 1 or n > POOL for n in nums):
        raise InvalidDraw(f"liczba spoza zakresu 1..{POOL}: {nums}")


def validate_draw(d: Draw) -> None:
    if d.draw_no < 1:
        raise InvalidDraw(f"niepoprawny numer losowania: {d.draw_no}")
    if not FIRST_DRAW <= d.date <= date.today():
        raise InvalidDraw(f"losowanie {d.draw_no}: data spoza zakresu: {d.date}")
    validate_numbers(d.numbers)
    if list(d.numbers) != sorted(d.numbers):
        raise InvalidDraw(f"losowanie {d.draw_no}: liczby nieposortowane: {d.numbers}")
    if d.order is not None and tuple(sorted(d.order)) != d.numbers:
        raise InvalidDraw(f"losowanie {d.draw_no}: kolejność {d.order} nie pasuje do {d.numbers}")


def validate_sequence(draws: list[Draw]) -> list[str]:
    """Sprawdza ciągłość serii: unikalne numery, brak dziur, rosnące daty.

    Zwraca listę ostrzeżeń (pusta = seria poprawna).
    """
    issues: list[str] = []
    by_no = sorted(draws, key=lambda d: d.draw_no)
    seen: set[int] = set()
    for d in by_no:
        if d.draw_no in seen:
            issues.append(f"zduplikowany numer losowania {d.draw_no}")
        seen.add(d.draw_no)
    if by_no:
        missing = set(range(by_no[0].draw_no, by_no[-1].draw_no + 1)) - seen
        if missing:
            issues.append(f"brakujące losowania: {sorted(missing)[:20]}")
    for prev, cur in zip(by_no, by_no[1:]):
        if cur.date < prev.date:
            issues.append(f"data maleje: {prev.draw_no} {prev.date} -> {cur.draw_no} {cur.date}")
    return issues
