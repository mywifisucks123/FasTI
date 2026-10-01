#!/usr/bin/env bash
# =============================================================================
# FasTI – Threat & Crisis Intelligence Dashboard · Starter für macOS
#
#   ./start.sh              Daten holen, Server auf :8000 starten, Browser öffnen
#   ./start.sh --no-ai      nur regelbasierte Analyse
#   ./start.sh --no-loop    kein automatisches Nachladen im Hintergrund
#   ./start.sh --port 8080  anderer Port
#
# Beenden mit Strg+C (stoppt Server und Hintergrund-Polling).
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
VENV_DIR=".venv"
BACKEND_ARGS=""
LOOP=1

while [ $# -gt 0 ]; do
  case "$1" in
    --no-ai)   BACKEND_ARGS="--no-ai" ;;
    --no-loop) LOOP=0 ;;
    --port)    PORT="${2:?Port fehlt}"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
  shift
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
info() { printf '%s▸%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s▸ %s%s\n' "$c_ylw" "$*" "$c_off"; }
fail() { printf '%s✗ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }

# Optionale .env mit GEMINI_API_KEY=… / GROQ_API_KEY=… / AI_PROVIDER=…
if [ -f .env ]; then
  set -a; . ./.env; set +a
  info ".env geladen"
fi

# --- 1. Python & Abhängigkeiten ---------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "python3 nicht gefunden. Installieren mit:  xcode-select --install   oder   brew install python"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || fail "Python >= 3.9 benötigt (gefunden: $(python3 --version 2>&1))."

if [ ! -x "$VENV_DIR/bin/python" ]; then
  info "Lege virtuelle Umgebung an ($VENV_DIR) …"
  python3 -m venv "$VENV_DIR" || fail "venv konnte nicht erstellt werden."
fi
PY="$VENV_DIR/bin/python"

if ! "$PY" -c 'import feedparser, requests' >/dev/null 2>&1; then
  info "Installiere Abhängigkeiten (feedparser, requests) …"
  "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$PY" -m pip install --quiet feedparser requests || fail "pip-Installation fehlgeschlagen (Internetverbindung?)."
else
  info "Abhängigkeiten vorhanden"
fi

# Lokale KI (Ollama): App starten, falls installiert, und Modell einmalig laden
if [ "$BACKEND_ARGS" != "--no-ai" ] && { [ -d /Applications/Ollama.app ] || command -v ollama >/dev/null 2>&1; }; then
  if ! curl -s -o /dev/null --max-time 2 http://localhost:11434/api/tags; then
    info "Starte Ollama (lokale KI) …"
    if [ -d /Applications/Ollama.app ]; then open -g -a Ollama; else (ollama serve >/dev/null 2>&1 &); fi
    for _ in $(seq 1 30); do
      curl -s -o /dev/null --max-time 2 http://localhost:11434/api/tags && break
      sleep 1
    done
  fi
  "$PY" backend.py --setup-ollama || warn "Lokale KI nicht bereit – nutze Cloud-KI bzw. regelbasierte Analyse."
fi

# Port prüfen, bevor der (ggf. längere) Erstabruf läuft
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "Port $PORT ist belegt. Anderen Port wählen:  ./start.sh --port 8080"
fi

# --- 2. Datenabruf im Hintergrund ----------------------------------------------
# Das Dashboard öffnet sofort und füllt sich, während das Backend arbeitet
# (mit lokaler KI dauert der erste Durchlauf bis zu 20 Minuten).
LOOP_PID=""
SERVER_PID=""
TAIL_PID=""
cleanup() {
  trap - EXIT INT TERM
  echo
  info "Beende FasTI …"
  for pid in "$SERVER_PID" "$LOOP_PID" "$TAIL_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

touch backend.log
if [ "$LOOP" -eq 1 ]; then
  INTERVAL=$("$PY" -c 'import config; print(config.POLL_INTERVAL_MINUTES)')
  # shellcheck disable=SC2086
  "$PY" backend.py --loop $BACKEND_ARGS >>backend.log 2>&1 &
  info "Datenabruf läuft, danach alle ${INTERVAL} Min. ${c_dim}(Log: backend.log)${c_off}"
else
  # shellcheck disable=SC2086
  "$PY" backend.py $BACKEND_ARGS >>backend.log 2>&1 &
  info "Einmaliger Datenabruf läuft ${c_dim}(Log: backend.log)${c_off}"
fi
LOOP_PID=$!
# Fortschritt im Terminal mitlesen
tail -n 0 -f backend.log &
TAIL_PID=$!

# --- 3. Webserver ----------------------------------------------------------------
# Nur an localhost gebunden – das Dashboard ist nicht im Netzwerk erreichbar.
"$PY" -m http.server "$PORT" --bind 127.0.0.1 >>server.log 2>&1 &
SERVER_PID=$!

URL="http://localhost:${PORT}"
for _ in $(seq 1 50); do
  if curl -s -o /dev/null "$URL/"; then break; fi
  kill -0 "$SERVER_PID" 2>/dev/null || fail "Webserver konnte nicht starten (siehe server.log)."
  sleep 0.1
done

# --- 4. Browser ------------------------------------------------------------------
info "Dashboard läuft auf ${URL}  ${c_dim}(Strg+C zum Beenden)${c_off}"
if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
fi

wait "$SERVER_PID"
