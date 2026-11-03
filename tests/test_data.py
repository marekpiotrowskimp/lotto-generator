from datetime import date

import pytest

from lotto import config
from lotto.data import db, sources
from lotto.data.validate import Draw, InvalidDraw, validate_sequence

SORTED_CSV = """0001,27.01.1957,08,12,31,39,43,45
0002,03.02.1957,05,10,11,22,25,27
0003,10.02.1957,18,19,20,26,45,49
"""
ORDER_CSV = """0001,27.01.1957,45,43,39,31,12,08
0002,03.02.1957,27,25,22,11,10,05
0003,10.02.1957,49,18,45,26,20,19
"""
MBNET = """1. 27.01.1957 8,12,31,39,43,45
2. 03.02.1957 5,10,11,22,25,27
3. 10.02.1957 18,19,20,26,45,48
"""


def test_parse_wynikilotto_csv():
    rows = sources.parse_wynikilotto_csv(SORTED_CSV)
    assert rows[1] == (date(1957, 1, 27), (8, 12, 31, 39, 43, 45))
    assert len(rows) == 3


@pytest.mark.parametrize("line", [
    "0001,27.01.1957,08,12,31,39,43",        # 5 liczb
    "0001,27.01.1957,08,12,31,39,43,43",     # powtórzenie
    "0001,27.01.1957,08,12,31,39,43,50",     # poza zakresem
    "0001,27.01.1957,00,12,31,39,43,45",     # zero
])
def test_parse_rejects_invalid(line):
    with pytest.raises(ValueError):
        sources.parse_wynikilotto_csv(line)


def test_parse_rejects_duplicate_draw_no():
    with pytest.raises(ValueError, match="zduplikowany"):
        sources.parse_wynikilotto_csv(SORTED_CSV + "0003,10.02.1957,18,19,20,26,45,49\n")


def test_parse_mbnet_sorts_numbers():
    rows = sources.parse_mbnet("7. 10.03.1957 45,3,22,11,9,1")
    assert rows[7] == (date(1957, 3, 10), (1, 3, 9, 11, 22, 45))


def test_build_draws_keeps_order_only_from_threshold():
    draws = sources.build_draws(
        sources.parse_wynikilotto_csv(SORTED_CSV), sources.parse_wynikilotto_csv(ORDER_CSV), order_since=3
    )
    assert draws[0].order is None and draws[1].order is None
    assert draws[2].order == (49, 18, 45, 26, 20, 19)
    assert draws[2].numbers == (18, 19, 20, 26, 45, 49)


def test_build_draws_rejects_mismatched_files():
    bad = ORDER_CSV.replace("49,18,45", "48,18,45")
    with pytest.raises(InvalidDraw):
        sources.build_draws(
            sources.parse_wynikilotto_csv(SORTED_CSV), sources.parse_wynikilotto_csv(bad), order_since=1
        )


def test_build_draws_date_mismatch_warns_and_correction_applies():
    order = ORDER_CSV.replace("0002,03.02.1957", "0002,02.02.1957")
    warnings = []
    draws = sources.build_draws(sources.parse_wynikilotto_csv(SORTED_CSV),
                                sources.parse_wynikilotto_csv(order), 1, None, warnings)
    assert len(warnings) == 1 and draws[1].date == date(1957, 2, 3)
    warnings = []
    draws = sources.build_draws(sources.parse_wynikilotto_csv(SORTED_CSV),
                                sources.parse_wynikilotto_csv(order), 1, {2: {"date": "1957-02-02"}}, warnings)
    assert warnings == [] and draws[1].date == date(1957, 2, 2)


def test_compare_sources_finds_difference():
    diffs = sources.compare_sources(sources.parse_wynikilotto_csv(SORTED_CSV), sources.parse_mbnet(MBNET))
    assert [d["draw_no"] for d in diffs] == [3]


def test_draw_validation():
    with pytest.raises(InvalidDraw):
        Draw(1, date(1957, 1, 27), (12, 8, 31, 39, 43, 45))           # nieposortowane
    with pytest.raises(InvalidDraw):
        Draw(1, date(1950, 1, 1), (8, 12, 31, 39, 43, 45))            # przed pierwszym losowaniem
    with pytest.raises(InvalidDraw):
        Draw(1, date(1957, 1, 27), (8, 12, 31, 39, 43, 45), (1, 2, 3, 4, 5, 6))  # zła kolejność


def test_validate_sequence_detects_gaps_and_dates():
    a = Draw(1, date(1957, 2, 10), (1, 2, 3, 4, 5, 6))
    c = Draw(3, date(1957, 2, 3), (1, 2, 3, 4, 5, 6))
    issues = validate_sequence([a, c])
    assert any("brakujące" in i for i in issues)
    assert any("data maleje" in i for i in issues)
    assert validate_sequence([a]) == []


def test_db_roundtrip_and_upsert(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    draws = sources.build_draws(sources.parse_wynikilotto_csv(SORTED_CSV), None, order_since=1)
    assert db.upsert_draws(conn, draws, "test") == 3
    assert db.upsert_draws(conn, draws, "test") == 0          # idempotentne
    with_order = sources.build_draws(
        sources.parse_wynikilotto_csv(SORTED_CSV), sources.parse_wynikilotto_csv(ORDER_CSV), order_since=3
    )
    db.upsert_draws(conn, with_order, "test")                  # uzupełnia kolejność
    loaded = db.load_draws(conn)
    assert loaded == with_order
    assert db.load_draws(conn, since=date(1957, 2, 1))[0].draw_no == 2


def test_config_rules_by_date():
    assert config.ticket_price(date(2026, 8, 18)) == 3.00   # losowanie 18.08 jeszcze po starej cenie
    assert config.ticket_price(date(2026, 8, 20)) == 5.00
    assert config.fixed_prizes(date(2026, 10, 10))["prize_3"] == 35
    assert config.fixed_prizes(date(2020, 1, 1))["prize_3"] == 24
