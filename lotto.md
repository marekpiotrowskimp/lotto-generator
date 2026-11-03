# Projekt LOTTO — analiza, backtest i strategia gry w Dużego Lotka

> Dokument projektowy (przed implementacją). Opisuje cel, założenia, zasady gry, metodologię,
> architekturę aplikacji i plan prac.

---

## 1. Cel i hipoteza badawcza

**Cel użytkownika:** zwiększyć skuteczność trafień 3/4/5/6 w Dużym Lotku, poprawić ROI
i zmaksymalizować szansę na główną wygraną.

**Losowość nie jest założeniem projektu, tylko hipotezą do obalenia.**

- **H0 (hipoteza zerowa):** losowania są niezależne i jednostajne, czyli każda z
  C(49,6) = 13 983 816 kombinacji ma tę samą szansę bez względu na historię.
- **H1 (szukamy dowodów):** w losowaniach istnieje wykrywalna i **powtarzalna** prawidłowość,
  np. obciążenie konkretnych kul lub maszyny, zależność od poprzednich losowań, dryf w czasie
  albo struktura w kolejności losowania. Taka prawidłowość pozwalałaby trafiać częściej niż przy typowaniu losowym.

Aktywnie i wieloma metodami szukamy w danych obalenia H0 (sekcja 5). Ponieważ szukamy
intensywnie, musimy też chronić się przed fałszywymi odkryciami: przy setkach testów część
wyjdzie „istotna” przez czysty przypadek. Dlatego każde odkrycie przechodzi trzy kroki:

1. **Wykrycie** na danych treningowych (eksploracja bez ograniczeń).
2. **Potwierdzenie** na danych testowych, których eksploracja nie widziała, z korektą na liczbę testowanych hipotez.
3. **Wykorzystanie:** strategia zbudowana na odkryciu musi pobić losowy baseline
   w backteście na danych testowych (sekcja 6).

**Co projekt daje niezależnie od wyniku badania:**

1. **Odpowiedź popartą danymi**, czy i gdzie losowania odbiegają od losowości, oraz jak dużą
   anomalię dane są w stanie w ogóle wykryć (analiza mocy testów).
2. **Wyższą wypłatę przy trafieniu.** Wygrane za 4, 5 i 6 są dzielone między zwycięzców.
   Liczby niepopularne (np. > 31, bez wzorów na kuponie) oznaczają mniej współzwycięzców.
   To działa nawet wtedy, gdy H0 jest prawdziwa.
3. **Grę wtedy, gdy EV jest najwyższe**, czyli przy wysokich kumulacjach, oraz kontrolę budżetu.
4. **Plan pokrycia liczb** (systemy / wheeling): mając wybraną pulę liczb,
   gwarancję określonych trafień, jeśli padną liczby z puli.

**Definicja sukcesu projektu:** rzetelny werdykt w sprawie H0 (z wartościami p i mocą testów),
generator kuponów oparty na najlepszej strategii *potwierdzonej na danych testowych* oraz symulator ROI.
Jeśli H0 się utrzyma, strategia opiera się na dźwigniach EV z punktów 2–4. Projekt **nie** obiecuje zysku.

---

## 2. Zasady Dużego Lotka (Totalizator Sportowy)

> Zasady zmieniły się **18.08.2026** (cena 3 → 5 zł, trójka 24 → 35 zł, gwarantowana szóstka 2 → 3 mln zł).
> Wartości wraz z historią zmian są w `config.yaml`, a nie w kodzie. Źródło: wynikilotto.net.pl
> (artykuł o cenniku); do potwierdzenia w regulaminie Totalizatora.

| Element | Wartość |
|---|---|
| Format | 6 liczb z 49 (1–49) |
| Losowania | wtorek, czwartek, sobota, ok. 22:00 |
| Cena zakładu | **5 zł** (od 18.08.2026; wcześniej 3 zł); +1 zł opcja **Lotto Plus** |
| Zakłady na kuponie | 1–8 zakładów prostych |
| 3 trafienia | wygrana **stała**: 35 zł (wcześniej 24 zł) |
| 4 trafienia | wygrana zmienna (pula dzielona), np. 284,10 zł w losowaniu 7416 |
| 5 trafień | wygrana zmienna, np. 10 805,70 zł w losowaniu 7416 |
| 6 trafień | pula główna, min. 3 mln zł (wcześniej 2 mln); brak zwycięzcy → **kumulacja** |
| Lotto Plus | osobne losowanie, ta sama kombinacja, nagroda tylko za 6 (stała, 1 mln zł) |
| Zakłady systemowe | 7–12 liczb na kuponie, czyli wszystkie kombinacje 6-liczbowe z wybranych (np. 7 liczb → 7 zakładów) |
| Chybił-trafił | losowanie liczb przez terminal |
| Podatek | 10% od wygranej powyżej 2 280 zł (pobierany przy wypłacie) |

---

## 3. Matematyka

Prawdopodobieństwo k trafień na jeden zakład: `C(6,k)·C(43,6−k) / C(49,6)`.

| Trafienia | Liczba kombinacji | Szansa (1 zakład) |
|---|---|---|
| 3 | 246 820 | 1 : 56,66 |
| 4 | 13 545 | 1 : 1 032 |
| 5 | 258 | 1 : 54 201 |
| 6 | 1 | 1 : 13 983 816 |
| ≥ 3 | 260 624 | 1 : 53,66 |

**EV zakładu (5 zł), szacunkowo, z wygranymi z losowania 7416 (10.10.2026):**
- 3 trafienia: 35 / 56,66 ≈ **0,62 zł**
- 4 trafienia: 284,10 / 1 032 ≈ **0,28 zł**
- 5 trafień: 10 805,70 / 54 201 ≈ **0,20 zł**
- 6 trafień: J_netto / 13 983 816 × E[1 / liczba współzwycięzców]

Bez szóstki EV ≈ 1,09 zł z 5 zł. Żeby zakład był „na zero”, szóstka musiałaby dawać ok.
**3,91 zł × 13,98 mln ≈ 55 mln zł netto** dla jednego zwycięzcy. Po podatku i przy
uwzględnieniu podziału nagrody próg nominalny jest wyraźnie wyższy. Przy dużej kumulacji
sprzedaż kuponów rośnie, a z nią ryzyko podziału, więc EV rośnie wolniej niż kumulacja.
System policzy to na prawdziwych danych (sprzedaż, liczba zwycięzców) w module `ev.py`.

**Wnioski strategiczne wynikające z matematyki:**
- Powyższe prawdopodobieństwa obowiązują **przy prawdziwej H0**. Są punktem odniesienia,
  który próbujemy pobić.
- Więcej zakładów zwiększa szansę liniowo, ale koszt też rośnie liniowo. Tak samo działają
  zakłady systemowe: system 7 liczb to 7 zakładów za 35 zł, szansa na zakład się nie zmienia.
- Dźwignie EV działające niezależnie od wyniku badania: **moment gry** (kumulacja)
  i **mniejszy podział wygranej** (niepopularne liczby).
- Dodatkowa dźwignia, jeśli obalimy H0: **wyższe prawdopodobieństwo trafienia**
  dzięki wykrytej prawidłowości. Przykład: obciążenie, które podnosi szansę trafienia 3
  o 10%, podnosi EV za trójki z ~0,62 do ~0,68 zł. Symulator ROI policzy, jaka
  przewaga byłaby potrzebna, żeby gra miała dodatnie EV.

---

## 4. Dane

**Źródła** (sprawdzone 11.10.2026):
1. **wynikilotto.net.pl, pliki CSV** (źródło główne): `download/lotto.csv` (liczby posortowane)
   i `download/lotto_niesortowane.csv` (**kolejność wypadania kul**), pełna historia od 27.01.1957,
   format `0001,27.01.1957,08,12,31,39,43,45`. Prawdziwa kolejność kul jest dostępna
   **od losowania 4045 (10.01.2004)**; wcześniej plik „niesortowany” zawiera liczby posortowane.
2. **wynikilotto.net.pl, strony losowań** (`/lotto/wyniki/10-paz-2026/`): liczba zwycięzców
   i wygrane w każdym stopniu oraz łączna pula, **dostępne od 2014 r.** Dane do EV i modelu popularności liczb.
   Pobierane z 1 s przerwy między stronami; liczby ze strony są porównywane z bazą.
3. **Archiwum mbnet.com.pl** (`dl.txt` z Wayback Machine, do 09.09.2025): źródło kontrolne.
   Domena mbnet.com.pl już nie działa.
4. **Oficjalne API Totalizatora** (`developers.lotto.pl`, klucz API w `.env`): opcjonalne.
   Strona lotto.pl blokuje automatyczne zapytania (HTTP 403).

**Jakość danych:** porównanie źródeł 1 i 3 dało 15 rozbieżności na 7 246 losowań (zwykle jedna
liczba). Sprawdzone przez trzecie źródło (TVP.info, losowanie 7214) potwierdziło wersję z wynikilotto.
Rozbieżności są zapisywane w tabeli `disputes`, a analizy mogą pominąć sporne losowania.
Ręczne poprawki danych (np. data losowania 4323) są w `config.yaml` → `corrections`, każda z uzasadnieniem.

**Magazyn:** SQLite `data/lotto.db`
- `draws(draw_no, date, n1..n6, o1..o6, source, imported_at)`: `o1..o6` to kolejność kul (NULL przed 2004)
- `prizes(draw_no, tier, winners, amount)`: wygrane i liczba zwycięzców (do EV i modelu popularności)
- `draw_meta(draw_no, total_pool, jackpot, sales)`
- `disputes(draw_no, source, date, numbers)`: rozbieżności między źródłami
- `sync_log(ts, source, added, status, message)`

Wszystkie źródła są **niezaufane**: walidacja (6 unikalnych liczb z 1–49, poprawna data,
brak duplikatów numeru losowania).

---

## 5. Analiza historyczna: poszukiwanie obalenia H0

Moduł `analysis/` to zestaw **detektorów anomalii**. Każdy sprawdza inny sposób, w jaki
losowania mogłyby odbiegać od idealnej losowości. Wszystkie detektory działają w trybie
„train” (eksploracja) i „test” (potwierdzenie).

**5.1 Obciążenie pojedynczych liczb (fizyka kul i maszyny)**
- częstość każdej liczby: cała historia, okna kroczące 50/100/500 losowań oraz okresy
  między zmianami regulaminu lub sprzętu,
- test chi-kwadrat jednorodności i test dokładny (rozkład wielomianowy z symulacji),
- **dryf w czasie**: czy obciążenie pojawia się i znika (detekcja punktów zmiany, CUSUM).
  Możliwe przyczyny to wymiana kompletu kul albo maszyny,
- grupy fizyczne: cyfry na kuli (np. 8, 88-podobne kształty), kolor/zestaw, jeśli dostępny,
  liczby jednocyfrowe kontra dwucyfrowe (różna ilość farby).

**5.2 Zależność od poprzednich losowań**
- autokorelacja wystąpień każdej liczby (lag 1–20),
- „gorące/zimne” i **przerwy** (ile losowań od ostatniego wystąpienia): czy rozkład przerw
  zgadza się z geometrycznym,
- powtórzenia liczb z poprzedniego losowania wobec oczekiwanej wartości,
- informacja wzajemna między losowaniem t a t−1…t−k,
- łańcuch Markowa: czy przejścia liczba→liczba odbiegają od niezależności.

**5.3 Struktura wewnątrz kombinacji**
- częstość par i trójek wobec oczekiwanej (sieć współwystąpień),
- rozkład sumy, parzystości, niskie/wysokie, kolejne liczby, końcówki, odstępy między liczbami
  (test KS wobec rozkładu z symulacji),
- **kolejność losowania** (jeśli dostępne dane nieposortowane): czy pierwsze wylosowane kule
  różnią się od późniejszych.

**5.4 Kontekst losowania**
- dzień tygodnia, pora roku, rok, numer losowania, okres kumulacji,
- różnice między okresami (np. przed i po zmianach zasad z ostatnich lat).

**5.5 Przewidywalność modelem (test „czarnej skrzynki”)**
- modele ML (gradient boosting, regresja logistyczna, sieć prosta) przewidują, czy liczba
  padnie w kolejnym losowaniu, na podstawie dowolnych cech historycznych,
- miara: log-loss / AUC na danych testowych wobec modelu „każda liczba ma 6/49”,
- **test permutacyjny**: ten sam model uczony na danych z losowo przetasowaną kolejnością
  losowań. Jeśli model nie wypada lepiej niż na danych przetasowanych, nie znalazł struktury.

**5.6 Ochrona przed fałszywymi odkryciami**
- rejestr wszystkich testowanych hipotez (liczba testów jest jawna w raporcie),
- korekta na wielokrotne porównania (Benjamini–Hochberg; Bonferroni dla kluczowych wniosków),
- każde odkrycie z danych treningowych jest **zamrażane** (parametry zapisane) przed
  sprawdzeniem na danych testowych,
- **kontrola pozytywna**: generujemy sztuczne losowania z wstrzykniętym obciążeniem
  (np. jedna liczba +5%, zależność od poprzedniego losowania) i sprawdzamy, czy detektory je wykrywają,
- **analiza mocy**: przy ~7 000+ losowań oczekiwana częstość liczby to ~850 ± 27,
  więc pojedyncze obciążenie rzędu kilku procent jest na granicy wykrywalności.
  Raport podaje dla każdego detektora najmniejszą anomalię, jaką dane są w stanie wykryć.
  Brak odkrycia oznacza „brak anomalii większej niż X”, a nie „brak anomalii w ogóle”.

**Wynik:** raport z werdyktem dla każdej grupy hipotez: *odrzucamy H0 / brak podstaw do
odrzucenia*, z wartościami p (przed i po korekcie), wielkością efektu i mocą testu.

**Wynik pierwszego badania (11.10.2026, losowania 1–7416):**
- train 1957–2020 (6 512 losowań), test 2021–10.10.2026 (904 losowania), 145 hipotez;
- p ≤ 0,05 na train: 13 testów (przy H0 przez przypadek ~7; testy są skorelowane, np. częstość i dryf tej samej liczby);
- po korekcie Benjaminiego–Hochberga istotnych na train: **0**, potwierdzonych na test: **0**;
- model przewidujący (5.5): gorszy od 6/49 na test, p_perm = 0,47; trafia średnio 0,728 z 6 (H0: 0,735);
- **werdykt: brak podstaw do odrzucenia H0.**

**Walidacja detektorów** (20 symulowanych historii o tych samych datach): fałszywe alarmy 0% (cel ≤ 5%),
odsetek p ≤ 0,05 przy H0 5,2% (cel ≈ 5%). Kontrola pozytywna: kula częstsza o 27% wykryta w 100%,
o 14% w 10%; powtórka liczby z poprzedniego losowania w 10% losowań wykryta w 90%.

**Moc:** protokół train → test wykrywa z prawdopodobieństwem 80% obciążenie pojedynczej liczby
≥ ~25%, grupy kul jednocyfrowych ≥ ~8%, zmianę liczby powtórzeń ≥ ~10%. Wąskim gardłem jest
mały zbiór testowy (904 losowania); test na całej historii wykryłby obciążenie liczby ≥ ~9%,
ale bez niezależnego potwierdzenia.

Moduły: `lotto/analysis/` (`detectors.py`, `ml.py`, `protocol.py`, `validate.py`).
Uruchomienie: strona „Analiza” albo `python -m lotto.analysis.protocol` i `python -m lotto.analysis.validate`.

---

## 6. Podział train/test i backtest

**Zasada:** wyłącznie **podział chronologiczny**, bez przecieku danych z przyszłości.

- **Train:** np. losowania do końca 2020 r.; **Test:** od 2021 r. do dziś (proporcje konfigurowalne).
- **Walk-forward:** przed każdym losowaniem testowym strategia widzi tylko wcześniejsze dane,
  generuje N zakładów, a system zapisuje trafienia.
- **Baseline losowy (Monte Carlo):** ta sama liczba zakładów losowanych jednostajnie,
  10 000 powtórzeń. Daje rozkład liczby trafień 3/4/5/6 oraz 95% przedział ufności.
- **Kryterium:** strategia „działa” tylko wtedy, gdy jej wynik na zbiorze **testowym**
  wychodzi poza 95% CI baseline'u (po korekcie na liczbę testowanych strategii).
  Wynik dobry tylko na train oznacza przeuczenie.

**Metryki:** liczba trafień 3/4/5/6, średnia trafień na zakład, symulowany ROI
(z prawdziwymi wypłatami z danego losowania), maksymalne obsunięcie budżetu, wartość p wobec baseline'u.

**Implementacja (`lotto/backtest/engine.py`):**
- strategia dostaje historię jako widoki tylko do odczytu (`DrawData.head(t)`), więc nie może zajrzeć w przyszłość
  (test: „szpieg” sprawdza długość historii; „wyrocznia” znająca wyniki jest wykrywana jako lepsza);
- baseline: **te same zakłady** sprawdzone na losowaniach symulowanych z H0. Przy H0 wynik prawdziwy i symulowany
  mają ten sam rozkład, więc p = odsetek symulacji z wynikiem co najmniej tak dobrym;
- ROI: wygrane z danego losowania (3: stała; 4–5: kwota·w/(w+1), bo dołączamy do zwycięzców; 6 bez zwycięzcy:
  gwarantowana pula jako ostrożny szacunek), podatek 10% powyżej 2 280 zł, cena zakładu z dnia losowania;
- porównanie wielu strategii: korekta Bonferroniego na liczbę strategii.

**Pierwsze wyniki (test 2021–2026, 904 losowania × 5 zakładów, parametry domyślne):**
| Strategia | Śr. trafień (H0 0,7347) | p | ≥3 trafienia | ROI |
|---|---|---|---|---|
| losowa | 0,7369 | 0,41 | 83 | −78% |
| gorące (okno 100) | 0,7374 | 0,44 | 93 | −76% |
| zimne (okno 100) | 0,7352 | 0,51 | 73 | −86% |

Żadna nie odbiega od losowości; ROI przy H0 (mediana) ≈ −80%. Różnice ROI między strategiami
mieszczą się w przedziale losowym.

---

## 7. Strategie (architektura pluginów)

Każda strategia implementuje interfejs `Strategy.generate(history, n_tickets) -> list[ticket]`.

| Strategia | Opis | Co testuje / co daje |
|---|---|---|
| `random` | jednostajne losowanie (baseline) | punkt odniesienia |
| `hot` | najczęstsze liczby w oknie | obciążenie trwałe lub dryfujące (5.1) |
| `cold` / `overdue` | najrzadsze / najdłużej niewylosowane | „wyrównywanie” i zależność od historii (5.2) |
| `pairs` | najczęstsze pary i trójki | struktura wewnątrz kombinacji (5.3) |
| `markov` | przejścia między kolejnymi losowaniami | zależność od poprzednich losowań (5.2) |
| `ml` | model na cechach historycznych | dowolna struktura wykryta w 5.5 |
| `discovered` | budowana automatycznie z anomalii potwierdzonych na danych testowych | wykorzystanie obalenia H0 |
| `balanced` | filtry rozkładu (suma, parzystość, niskie/wysokie) | struktura cech kombinacji |
| **`anti_popular`** | unika liczb i wzorów często wybieranych przez graczy | **wyższa oczekiwana wypłata przy trafieniu** (działa niezależnie od H0) |

Strategie można **łączyć**, np. `discovered` wybiera pulę liczb z przewagą, a `anti_popular`
układa z niej kombinacje rzadko typowane przez innych.

**Wyniki backtestu (test 2021–2026, 904 losowania × 5 zakładów, parametry domyślne, 300 symulacji H0):**

| Strategia | Śr. trafień (H0 0,7347) | p | p (Bonferroni ×9) | ≥3 trafienia | ROI | ROI H0 (mediana) |
|---|---|---|---|---|---|---|
| random | 0,7369 | 0,41 | 1,00 | 83 | −78% | −80% |
| hot | 0,7374 | 0,44 | 1,00 | 93 | −76% | −80% |
| cold | 0,7352 | 0,51 | 1,00 | 73 | −86% | −80% |
| pairs | 0,7427 | 0,29 | 1,00 | 96 | −77% | −81% |
| markov | 0,7374 | 0,43 | 1,00 | 84 | −84% | −81% |
| ml | 0,7082 | 0,92 | 1,00 | 82 | −84% | −81% |
| balanced | 0,7383 | 0,45 | 1,00 | 82 | −84% | −80% |
| anti_popular | 0,7566 | 0,09 | 0,84 | 95 | **−73%** | −80% |
| discovered | brak anomalii z etapu 3 → zakłady losowe | | | 83 | −78% | −80% |

Żadna strategia nie trafia istotnie częściej niż przypadek. Różnice ROI mieszczą się w przedziale
losowym (za mało trafień 4–5 w 904 losowaniach, by ROI rozróżniło strategie).

**Model popularności (`lotto/analysis/popularity.py`)** to jedyny wynik istotny poza próbą:
- sygnał: liczba zwycięzców z trójką względem mediany sąsiednich losowań; poprawka na kumulację (sprzedaż);
  regresja grzbietowa na wylosowanych liczbach + cechach kombinacji;
- model z 2014–2020 (1 077 losowań) przewiduje na 2021–2026 (904): korelacja **0,39**, p < 0,001
  (sama popularność liczb, bez efektu kumulacji);
- najpopularniejsze: 13, 7, 5, 4, 12, 21, 3, 6 (daty, „szczęśliwe” liczby); najmniej: 45, 46, 38, 42, 43, 49, 30, 40;
- mediana wygranej za 4 w losowaniach testowych: **247 zł** gdy wylosowane liczby były w 20% najmniej popularnych
  vs **113 zł** w 20% najpopularniejszych; za 5: 6 451 zł vs 4 711 zł;
- generator podaje dla zakładu mnożnik wygranej przy trafieniu, ograniczony do zakresu obserwowanego w danych
  (zakłady `anti_popular`: ~×2 za 4, ~×1,35 za 5).

**Pokrycie puli (`lotto/strategies/wheel.py`):** zachłanne pokrycie z wyczerpującą weryfikacją gwarancji,
np. pula 10 liczb: „3 jeśli 4” w 4 zakładach, „4 jeśli 5” w 7 (pełny system: 210).

**Model popularności (dla `anti_popular`):** gracze nadreprezentują liczby 1–31 (daty),
wzory geometryczne na kuponie, ciągi arytmetyczne, liczby „szczęśliwe” (7, 13) i ostatnie
wyniki. Popularność oszacujemy z historii: liczba zwycięzców 4/5 w losowaniu względem
oczekiwanej wynikającej ze sprzedaży. Losowania z „popularnymi” liczbami mają więcej zwycięzców.

---

## 8. Strategia rekomendowana i ROI

Strategia zależy od werdyktu z sekcji 5–6:

- **Scenariusz A: H0 obalona** (anomalia potwierdzona na danych testowych i pobijająca
  baseline w backteście). Rdzeniem jest strategia `discovered`: pula liczb i kombinacje
  wynikające z wykrytej prawidłowości. Na tę przewagę nakładamy punkty 1–5 poniżej.
  Przewagę monitorujemy na bieżąco: po każdej synchronizacji system sprawdza, czy anomalia
  nadal występuje w nowych losowaniach (np. po wymianie kul może zniknąć).
- **Scenariusz B: brak podstaw do odrzucenia H0.** Strategia opiera się wyłącznie na
  punktach 1–5. Badanie anomalii trwa dalej: każde nowe losowanie wydłuża dane i zwiększa moc testów.

Elementy wspólne (do potwierdzenia backtestem i symulatorem):

1. **Stały budżet** na okres (np. miesiąc). Nie zwiększamy stawek po przegranej.
2. **Gra selektywna:** wyłącznie gdy kumulacja przekracza próg z modułu EV.
   Daje to najwyższe EV na wydaną złotówkę.
3. **Kombinacje `anti_popular`:** jeśli trafimy, dzielimy wygraną z mniejszą liczbą osób.
4. **Pokrycie (wheeling):** dla wybranej puli np. 10–12 liczb generujemy skrócony system
   z gwarancją (np. „3 trafienia, jeśli 4 z wylosowanych są w puli”) za ułamek kosztu pełnego systemu.
   Nie zwiększa to EV, ale wygładza wyniki.
5. **Lotto Plus:** opłacalność dodatkowej złotówki liczona osobno (stała nagroda 1 mln zł,
   EV ≈ 0,07 zł za 1 zł, czyli zwykle się nie opłaca; system to policzy).

**Symulator ROI** (`lotto/roi_sim.py`, strona „ROI”) odtwarza politykę gry na prawdziwych losowaniach
(walk-forward, faktyczne wygrane) i liczy ROI oczekiwane przy faktycznych poziomach wygranych w każdym losowaniu.

**Odtworzenie kumulacji** (`lotto/analysis/jackpot.py`): po wygranej pula wraca do minimum, w losowaniu z wygraną
= zwycięzcy × kwota, pomiędzy rośnie proporcjonalnie do sprzedaży (≈ zwycięzcy z trójką / P(3)).
Sprawdzian: oczekiwana liczba szóstek ze sprzedaży 0,229 na losowanie vs 0,248 w danych.
Sprzedaż rośnie z kumulacją (~J^0,35): 2,1 mln zakładów przy 2 mln zł, 6,5 mln przy 50 mln zł.

**EV zakładu** (`lotto/ev.py`, zasady od 20.08.2026: 5 zł, trójka 35 zł; mediany czwórki 334 zł i piątki 10 078 zł):
- przy kumulacji 8 mln zł (13.10.2026): zakład losowy 1,57 zł (ROI −69%), niepopularny 1,98 zł (ROI −60%);
- próg opłacalności: **78 mln zł** (losowy), **65 mln zł** (niepopularny); najwyższa kumulacja od 2014 r.: 57,8 mln zł;
- Lotto Plus: EV 0,064 zł za 1 zł (ROI −94%) — nie opłaca się nigdy.

**ROI oczekiwane wg progu kumulacji (2014–2026, 1 980 losowań, zasady z dnia losowania):**

| Graj, gdy kumulacja ≥ | Losowań | Zakład losowy | Zakład niepopularny |
|---|---|---|---|
| zawsze | 1 980 | −64% | −56% |
| 10 mln zł | 428 | −48% | −39% |
| 20 mln zł | 90 | −32% | −22% |
| 30 mln zł | 17 | −19% | −8% |
| 40 mln zł | 3 | −9% | +2% |

**Rekomendacja (scenariusz B: H0 utrzymana):**
1. Grać wyłącznie przy wysokiej kumulacji: każde podniesienie progu poprawia ROI; dodatnie EV zdarza się
   bardzo rzadko (3 losowania w 12 lat przy zasadach sprzed 08.2026; przy obecnych zasadach próg to 65 mln zł).
2. Zawsze zakłady niepopularne (generator): +8–10 pkt proc. ROI dzięki mniejszemu podziałowi wygranych.
3. Bez Lotto Plus. Stały budżet; system/pokrycie tylko dla wygładzenia wyników, nie dla EV.
4. Zrealizowane ROI jest zdominowane przez rzadkie trafienia (np. 194 losowania × 5 zakładów przy progu 15 mln:
   ROI oczekiwane −30%, zrealizowane −81%, bo padły tylko trójki); to mieści się w pasie wyników losowych.

---

## 9. Architektura

- **Język:** Python 3.12
- **Backend:** FastAPI + Uvicorn (REST API i serwowanie statycznego frontendu)
- **Obliczenia:** pandas, numpy, scipy; scikit-learn (strategia `ml`)
- **Baza:** SQLite
- **Frontend:** HTML + vanilla JS + Chart.js (z CDN, bez kroku build)
- **Testy:** pytest

```
lotto/
├── run.sh                  # start aplikacji
├── requirements.txt
├── config.yaml             # zasady gry, ceny, progi, podział train/test
├── .env.example            # LOTTO_API_KEY=...
├── data/lotto.db
├── lotto/
│   ├── data/               # sources.py (mbnet, api, scraper), sync.py, db.py, validate.py
│   ├── analysis/           # frequency.py, gaps.py, pairs.py, stats_tests.py
│   ├── strategies/         # base.py, random.py, hot.py, cold.py, ml.py, anti_popular.py, wheel.py
│   ├── backtest/           # split.py, walk_forward.py, baseline.py, metrics.py
│   ├── ev.py               # EV zakładu wobec kumulacji
│   ├── roi_sim.py          # symulator polityk gry
│   └── api/                # app.py, routes
├── web/                    # index.html, analysis.html, backtest.html, generator.html, roi.html, js/, css/
└── tests/
```

**API (szkic):**
- `POST /api/sync`: pobranie brakujących losowań; zwraca liczbę dodanych
- `GET /api/draws?limit=`: ostatnie losowania
- `GET /api/analysis`: statystyki i testy
- `POST /api/backtest`: `{strategy, n_tickets, split_date}` → metryki oraz CI baseline'u
- `POST /api/generate`: `{strategy, n_tickets, budget}` → kupony
- `GET /api/ev`: EV następnego losowania przy bieżącej kumulacji
- `POST /api/roi`: `{policy}` → krzywa salda i metryki

---

## 10. Interfejs WWW (lokalnie)

1. **Dashboard:** ostatnie losowania, aktualna kumulacja, EV najbliższego losowania,
   przycisk **„Synchronizuj losowania”** (z informacją o ostatniej synchronizacji).
2. **Analiza:** wykresy częstości, przerw i rozkładu sum; heatmapa par; tabela testów z wartościami p.
3. **Backtest:** wybór strategii, liczby zakładów i daty podziału; wynik na tle rozkładu baseline'u.
4. **Generator kuponów:** strategia, liczba zakładów lub budżet, opcjonalna pula do wheelingu;
   kopiowanie i eksport (CSV / do druku).
5. **Symulator ROI:** parametry polityki (próg kumulacji, budżet, Lotto Plus) → krzywa salda.

---

## 11. Skrypt `run.sh`

`./run.sh`:
1. jeśli aplikacja już działa na którymś porcie 8000–8020, tylko otwiera przeglądarkę;
2. wybiera pierwszy wolny port od 8000 (np. gdy 8000 zajmuje inny program); port można wymusić: `PORT=9000 ./run.sh`;
3. tworzy `.venv`, instaluje `requirements.txt`;
4. przy pierwszym uruchomieniu importuje pełną historię losowań (`python -m lotto.data.sync --if-empty`);
5. uruchamia serwer na `127.0.0.1` (tylko lokalnie) i otwiera przeglądarkę.

Wygrane (od 2014 r.) pobiera się przyciskiem „Synchronizuj losowania” na dashboardzie albo
`python -m lotto.data.sync --prizes` (pierwszy raz ~2 000 stron z przerwą 1 s, ~35 min).

---

## 12. Plan implementacji

| Etap | Zakres | Kryterium akceptacji |
|---|---|---|
| 1 | Szkielet repo, `config.yaml`, SQLite, import CSV (wynikilotto), porównanie z archiwum mbnet, walidacja | baza zawiera pełną historię; testy walidacji przechodzą ✅ |
| 2 | Synchronizacja, wygrane i liczba zwycięzców (od 2014 r.), kumulacja, dashboard WWW, `run.sh` | `POST /api/sync` dodaje tylko brakujące losowania i wygrane ✅ |
| 3 | Detektory anomalii (5.1–5.5), rejestr hipotez, korekty, analiza mocy, strona „Analiza” | kontrola pozytywna: detektory wykrywają wstrzyknięte obciążenie; na danych w pełni losowych odsetek fałszywych alarmów ≤ 5% ✅ |
| 4 | Backtest: split, walk-forward, baseline Monte Carlo, ROI na prawdziwych wygranych, strona „Backtest” | strategia `random` mieści się w CI baseline'u (test poprawności) ✅ |
| 5 | Strategie: hot/cold/pairs/markov/ml/discovered/balanced/anti_popular, model popularności, wheeling, generator kuponów | każda strategia zbacktestowana na danych testowych; raport porównawczy ✅ |
| 6 | EV vs kumulacja, odtworzenie kumulacji, symulator polityk gry, strona „ROI” | ROI zgodny z ręcznym przeliczeniem dla próbki losowań ✅ (testy jednostkowe) |
| 7 | Frontend (5 widoków) i `run.sh` | `./run.sh` uruchamia stronę; synchronizacja działa z UI ✅ (budowane na bieżąco w etapach 2–6) |
| 8 | Raport końcowy: werdykt w sprawie H0, wybrana strategia i uzasadnienie | wnioski poparte liczbami z danych testowych ✅ (sekcja 14); automatyczny monitoring anomalii po synchronizacji **nie zrealizowany**: analizę uruchamia się przyciskiem na stronie „Analiza” |

---

## 13. Zastrzeżenie i odpowiedzialna gra

Dopóki H0 nie zostanie obalona na danych testowych, Lotto należy traktować jako grę losową
o ujemnej wartości oczekiwanej. Narzędzie służy do badania tej hipotezy i do świadomego
wyboru: kiedy grać, jak nie dzielić się wygraną i ile wydać.
Nie gwarantuje wygranej ani dodatniego zwrotu. Ustal stały budżet i traktuj go jako koszt rozrywki.

---

## 14. Raport końcowy (11.10.2026)

### Pytanie
Czy w historycznych losowaniach Dużego Lotka są prawidłowości, które pozwalają trafiać 3–6
częściej niż przypadek, i czy da się zbudować system gry o dodatnim zwrocie z inwestycji?

### Odpowiedź
**Nie.** Losowania zachowują się jak czysty przypadek, a żadna strategia typowania nie trafia częściej
niż losowe skreślenia. Gra ma ujemną wartość oczekiwaną; da się jedynie **zmniejszyć stratę**
(wybór momentu gry i niepopularnych kombinacji), ale nie odwrócić jej. **Lotto nie jest inwestycją.**

### Dane
- 7 416 losowań (27.01.1957 – 10.10.2026), źródło główne: wynikilotto.net.pl (CSV); kontrolne: archiwum mbnet;
  15 rozbieżności między źródłami (0,2%), sprawdzona jedna (wersja główna potwierdzona przez TVP.info);
- kolejność wypadania kul: 3 372 losowania (od 2004 r.);
- wygrane i liczba zwycięzców: 1 981 losowań (2014–2026), liczby na stronach zgodne z bazą w 100%.

### Wyniki
1. **Test losowości (H0)**: 145 hipotez (obciążenie liczb i grup kul, dryf, zależność od poprzednich losowań,
   pary, przerwy, cechy kombinacji, kolejność kul, kontekst, model ML). Protokół train (1957–2020) → test (2021–2026)
   z korektą na wielokrotne porównania: **0 anomalii potwierdzonych**. Detektory zwalidowane: 0% fałszywych alarmów
   na danych losowych, wykrywają wstrzyknięte obciążenia ≥ ~25% (jedna liczba) i ~10% (powtórki).
2. **Backtest 9 strategii** (gorące, zimne, pary, Markow, ML, zrównoważone, niepopularne, odkryte, losowa)
   na 904 losowaniach testowych: żadna nie trafia istotnie częściej niż przypadek (najlepsze p po korekcie 0,84).
3. **Popularność liczb wśród graczy** — jedyny istotny wynik: model z 2014–2020 przewiduje liczbę zwycięzców
   w 2021–2026 (korelacja 0,39, p < 0,001). Gracze nadreprezentują 13, 7, 5, 4, 12, 21, 3, 6 (daty, „szczęśliwe”),
   unikają 45, 46, 38, 42, 43, 49, 30, 40. Mediana wygranej za 4: 247 zł przy niepopularnych liczbach vs 113 zł
   przy popularnych. **Nie zmienia szansy trafienia, zmienia wypłatę przy trafieniu.**
4. **Opłacalność**: przy obecnych zasadach (5 zł) zakład ma dodatnie EV dopiero przy kumulacji 65 mln zł
   (niepopularny) / 78 mln zł (losowy); najwyższa kumulacja od 2014 r. to 57,8 mln zł. Dodatnie EV i tak nie
   przekłada się na zysk zwykłego gracza: prawie cała wartość leży w szóstce (1 : 13 983 816).

### Rekomendacja (dla grających dla rozrywki)
- grać rzadko, tylko przy wysokiej kumulacji (ROI oczekiwane: −64% przy grze w każdym losowaniu,
  −39% przy progu 10 mln zł, −22% przy 20 mln zł);
- zakłady niepopularne z generatora (+8–10 pkt proc. ROI);
- bez Lotto Plus (ROI −94%);
- stały budżet traktowany jako koszt rozrywki. Przykład: 5 zakładów w każdym losowaniu to ~3 900 zł rocznie
  i średnio ~2 400–2 700 zł straty; 5 zakładów tylko przy kumulacji ≥ 15 mln zł to ~400 zł rocznie i ~120 zł straty.

### Ograniczenia
- zbiór testowy (904 losowania) wykrywa obciążenie pojedynczej liczby dopiero od ~25%; mniejszych anomalii
  nie da się wykluczyć, ale też nie dałoby się ich wykorzystać przy ujemnym EV;
- kumulacja w losowaniach bez wygranej jest odtworzona (interpolacja wg sprzedaży), sprzedaż szacowana z trójek;
- mnożnik wygranej dla zakładów niepopularnych to ostrożny szacunek ograniczony do zakresu danych;
- brak danych o losowaniach Lotto Plus (liczony tylko oczekiwany zwrot);
- źródła danych nieoficjalne (lotto.pl blokuje pobieranie, oficjalne API wymaga klucza); 14 z 15 rozbieżności
  nierozstrzygniętych; zasady i ceny do potwierdzenia w regulaminie Totalizatora;
- brak automatycznego monitoringu anomalii po synchronizacji (analiza uruchamiana ręcznie).

### Aplikacja
`./run.sh` → Dashboard (synchronizacja, ostatnie losowania), Analiza (werdykt H0, wykresy, hipotezy, moc,
walidacja), Backtest (strategie vs losowość), Generator (kupon niepopularny, pokrycie puli), ROI (EV vs kumulacja,
progi gry, symulator polityki). Testy: `.venv/bin/python -m pytest` (69 testów).

