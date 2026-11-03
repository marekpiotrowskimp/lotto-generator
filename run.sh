#!/usr/bin/env bash
# Uruchamia lokalną aplikację Lotto (domyślnie http://127.0.0.1:8000).
# Jeśli port jest zajęty przez inny program, wybiera kolejny wolny.
# Port można wymusić: PORT=8100 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

HOST=127.0.0.1
PORT="${PORT:-8000}"

port_busy() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

is_lotto() {
  curl -s -m 2 "http://${HOST}:$1/api/status" 2>/dev/null | grep -q '"draws"'
}

# Lotto już działa na którymś z portów? Wtedy tylko otwieramy przeglądarkę.
for p in $(seq "$PORT" $((PORT + 20))); do
  if port_busy "$p" && is_lotto "$p"; then
    echo "Aplikacja Lotto już działa: http://${HOST}:${p}"
    open "http://${HOST}:${p}"
    exit 0
  fi
done

# Pierwszy wolny port od PORT w górę.
for p in $(seq "$PORT" $((PORT + 20))); do
  if ! port_busy "$p"; then
    [ "$p" != "$PORT" ] && echo "Port ${PORT} jest zajęty przez inny program, używam ${p}."
    PORT="$p"
    break
  fi
  if [ "$p" = $((PORT + 20)) ]; then
    echo "Brak wolnego portu w zakresie ${PORT}-$((PORT + 20)). Ustaw inny: PORT=9000 ./run.sh" >&2
    exit 1
  fi
done

if [ ! -d .venv ]; then
  echo "Tworzę środowisko Python (.venv)..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt

# Pierwsze uruchomienie: import pełnej historii losowań (kilka sekund).
python -m lotto.data.sync --if-empty

( sleep 2 && open "http://${HOST}:${PORT}" ) >/dev/null 2>&1 &
echo "Aplikacja: http://${HOST}:${PORT}  (Ctrl+C kończy)"
exec uvicorn lotto.api.app:app --host "$HOST" --port "$PORT"
