# lotto-generator

Statistical analysis of Polish **Lotto** draws (6 of 49), strategy backtesting and a bet generator, with a local web UI.

The project treats randomness as a hypothesis to be refuted: it looks for deviations from a uniform distribution,
confirms them on held-out test data (with multiple-testing correction) and compares strategies against a random baseline.
It also provides practical tools: picking unpopular numbers (a higher payout if you win), coverage systems (wheeling) and budget control.

> This is a research tool. Lotteries have a negative expected value — no program changes that.

## Features

- Analysis of historical draws (`lotto/analysis`) with statistical tests
- Strategy backtests on train/test splits (`lotto/backtest`, `lotto/strategies`)
- Expected value and ROI simulation, including prizes, Lotto Plus and tax (`lotto/ev.py`, `lotto/roi_sim.py`, `config.yaml`)
- Bet generator with a bookmarklet that fills a bet on lotto.pl (`lotto/generator.py`)
- Web pages: analysis, backtest, generator, ROI (`web/`)

Design document (in Polish): [lotto.md](lotto.md).

## Running

```sh
./run.sh            # creates .venv, installs dependencies, starts the web app (http://127.0.0.1:8000)
PORT=8100 ./run.sh  # force a different port
pytest              # tests
```

## License

MIT — see [LICENSE](LICENSE).
