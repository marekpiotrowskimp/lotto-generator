from datetime import date

import pytest
from fastapi.testclient import TestClient

from lotto import config
from lotto.data import db, prizes, sources

PAGE = """
<dl>
<dt>Numer losowania</dt>
<dd>6668</dd>
<dt>Całkowita pula PLN</dt>
<dd>11 861 121 zł</dd>
<dt>Data losowania</dt>
<dd>30.12.2021</dd>
</dl>
<table class="tabela cs9"><tbody>
<tr class="trzw"><td>I: 6/6 (szóstka)</td><td>1 <a href="/lotto/najwyzsze-wygrane/">&#127757;</a></td><td>9 345 079,70</td></tr>
<tr class="trzw"><td>II: 5/6 (piątka)</td><td>68</td><td>5 285,50</td></tr>
<tr class="trzw"><td>III: 4/6 (czwórka)</td><td>3562</td><td>177,80</td></tr>
<tr class="trzw"><td>IV: 3/6 (trójka)</td><td>63471</td><td>24,00
</td></tr>
</tbody></table>
<p><strong>Wyniki Lotto 30.12.2021 to:</strong> 2, 9, 16, 28, 39, 45. Numer losowania to: 6668.</p>
"""

PAGE_NO_DATA = """
<dl><dt>Numer losowania</dt><dd>1</dd>
<dt>Całkowita pula PLN</dt><dd>Czekamy na informacje o wygranych... <a>Odśwież</a></dd>
<dt>Data losowania</dt><dd>27.01.1957</dd></dl>
<p><strong>Wyniki Lotto 27.01.1957 to:</strong> 8, 12, 31, 39, 43, 45. Numer losowania to: 1.</p>
"""


def test_slug():
    assert prizes.slug(date(2026, 10, 10)) == "10-paz-2026"
    assert prizes.slug(date(1957, 1, 27)) == "27-sty-1957"


def test_parse_draw_page_with_prizes():
    p = prizes.parse_draw_page(PAGE)
    assert (p.draw_no, p.date) == (6668, date(2021, 12, 30))
    assert p.numbers == (2, 9, 16, 28, 39, 45)
    assert p.total_pool == 11861121.0
    assert p.prizes == {6: (1, 9345079.70), 5: (68, 5285.50), 4: (3562, 177.80), 3: (63471, 24.00)}


def test_parse_draw_page_without_prizes():
    p = prizes.parse_draw_page(PAGE_NO_DATA)
    assert p.prizes == {} and p.total_pool is None and p.draw_no == 1


def test_parse_draw_page_rejects_partial_table():
    with pytest.raises(ValueError, match="niepełna"):
        prizes.parse_draw_page(PAGE.replace("<tr class=\"trzw\"><td>II: 5/6", "<tr><td>X"))


def test_parse_current_jackpot():
    assert prizes.parse_current_jackpot("<li>Kumulacja Lotto <b>8 000 000 zł</b></li>") == 8_000_000
    assert prizes.parse_current_jackpot("<p>nic</p>") is None


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(config, "db_path", lambda: path)
    c = db.connect(path)
    rows = sources.parse_wynikilotto_csv("6667,28.12.2021,01,02,03,04,05,06\n6668,30.12.2021,02,09,16,28,39,45\n")
    db.upsert_draws(c, sources.build_draws(rows, None, 1), "test")
    return c


def test_fetch_prizes_saves_and_skips(conn, monkeypatch):
    pages = {"28-gru-2021": PAGE_NO_DATA.replace("<dd>1</dd>", "<dd>6667</dd>").replace("27.01.1957", "28.12.2021").replace("8, 12, 31, 39, 43, 45", "1, 2, 3, 4, 5, 6"),
             "30-gru-2021": PAGE}
    monkeypatch.setattr(sources, "fetch_text", lambda url: pages[url.rstrip("/").rsplit("/", 1)[1]])
    stats = prizes.fetch_prizes(conn, since=date(2021, 1, 1), delay=0)
    assert (stats["ok"], stats["no_data"], stats["error"], stats["mismatch"]) == (1, 1, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM prizes WHERE draw_no = 6668").fetchone()[0] == 4
    # drugi przebieg: 6668 ma dane, 6667 (stare, bez danych) nie jest pobierane ponownie
    assert prizes.draws_to_fetch(conn, date(2021, 1, 1)) == []


def test_fetch_prizes_detects_wrong_page(conn, monkeypatch):
    monkeypatch.setattr(sources, "fetch_text", lambda url: PAGE)  # zawsze strona losowania 6668
    stats = prizes.fetch_prizes(conn, since=date(2021, 1, 1), delay=0)
    assert stats["error"] == 1 and stats["ok"] == 1


def test_api_status_and_draws(conn):
    from lotto.api.app import app
    db.save_prizes(conn, 6668, {6: (1, 9345079.7), 5: (68, 5285.5), 4: (3562, 177.8), 3: (63471, 24.0)}, 11861121.0)
    client = TestClient(app)
    s = client.get("/api/status").json()
    assert s["draws"] == 2 and s["draws_with_prizes"] == 1 and s["last_draw"]["draw_no"] == 6668
    d = client.get("/api/draws?limit=1").json()
    assert d[0]["numbers"] == [2, 9, 16, 28, 39, 45]
    assert d[0]["prizes"]["6"]["winners"] == 1
    assert client.get("/").status_code == 200
