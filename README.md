# lotto-generator

Analiza statystyczna losowań **Dużego Lotka**, backtest strategii i generator zakładów.

Projekt traktuje losowość jako hipotezę do obalenia: szuka odchyleń od rozkładu jednostajnego,
potwierdza je na danych testowych (z korektą na wielokrotne testowanie) i porównuje strategie z losowym baseline.
Daje też praktyczne narzędzia: wybór niepopularnych liczb (wyższa wypłata przy trafieniu), systemy pokrycia, kontrolę budżetu.

> To narzędzie badawcze. Gry liczbowe mają ujemną wartość oczekiwaną — żaden program jej nie odwraca.

Dokument projektowy: [lotto.md](lotto.md).

## Uruchomienie

```sh
./run.sh            # tworzy venv, instaluje zależności, uruchamia panel webowy
pytest              # testy
```
