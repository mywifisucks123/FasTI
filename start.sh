#!/usr/bin/env bash
# =============================================================================
# FasTI – Threat & Crisis Intelligence Dashboard · Starter für macOS
#
#   bash start.sh                Daten holen, Dashboard auf :8000 starten, Browser öffnen
#   bash start.sh --autostart    FasTI bei jedem Mac-Start automatisch im Hintergrund starten
#   bash start.sh --autostart-aus  Autostart wieder entfernen
#   bash start.sh --test-push    Test-Benachrichtigung an Mac und iPhone senden
#   bash start.sh --no-ai        nur regelbasierte Analyse
#   bash start.sh --no-loop      kein automatisches Nachladen im Hintergrund
#   bash start.sh --port 8080    anderer Port
#
# Beenden mit Strg+C (stoppt Server und Hintergrund-Polling).
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"

PORT="${PORT:-8000}"
VENV_DIR=".venv"
BACKEND_ARGS=""
LOOP=1
HEADLESS=0
MODE="run"
LABEL="de.fasti.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

while [ $# -gt 0 ]; do
  case "$1" in
    --no-ai)          BACKEND_ARGS="--no-ai" ;;
    --no-loop)        LOOP=0 ;;
    --port)           PORT="${2:?Port fehlt}"; shift ;;
    --headless)       HEADLESS=1 ;;
    --autostart)      MODE="autostart" ;;
    --autostart-aus)  MODE="autostart_off" ;;
    --test-push)      MODE="test_push" ;;
    -h|--help)        sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
  shift
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
[ "$HEADLESS" -eq 1 ] && { c_red=""; c_grn=""; c_ylw=""; c_dim=""; c_off=""; }
info() { printf '%s▸%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s▸ %s%s\n' "$c_ylw" "$*" "$c_off"; }
fail() { printf '%s✗ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }
URL="http://localhost:${PORT}"
open_browser() {
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  fi
}

# --- Autostart entfernen ------------------------------------------------------
if [ "$MODE" = "autostart_off" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  info "Autostart entfernt. FasTI läuft nicht mehr im Hintergrund."
  exit 0
fi

# Optionale .env mit GEMINI_API_KEY=… / GROQ_API_KEY=… / AI_PROVIDER=…
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# --- 1. Python & Abhängigkeiten ---------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "python3 nicht gefunden. Installieren mit:  xcode-select --install"
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
fi

# --- Test-Push ------------------------------------------------------------------
if [ "$MODE" = "test_push" ]; then
  "$PY" backend.py --test-push
  exit 0
fi

# --- Autostart einrichten ------------------------------------------------------
if [ "$MODE" = "autostart" ]; then
  case "$APP_DIR" in
    "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
      fail "macOS erlaubt Hintergrunddiensten keinen Zugriff auf Schreibtisch, Dokumente und Downloads.
  Bitte den Ordner FasTI im Finder in deinen Benutzerordner (Haus-Symbol) verschieben und dann:
    cd ~/FasTI && bash start.sh --autostart" ;;
  esac
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && [ ! -f "$PLIST" ]; then
    fail "FasTI läuft gerade in einem anderen Terminal-Fenster. Dort erst mit Strg+C beenden, dann erneut ausführen."
  fi
  mkdir -p "$HOME/Library/LaunchAgents"
  cat >"$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$APP_DIR/start.sh</string>
    <string>--headless</string>
    <string>--port</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key><string>$APP_DIR/autostart.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/autostart.log</string>
</dict>
</plist>
PLISTEOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST" || fail "Autostart konnte nicht aktiviert werden."
  info "Autostart aktiv – FasTI startet ab jetzt mit dem Mac und läuft ohne Terminal."
  for _ in $(seq 1 120); do
    curl -s -o /dev/null --max-time 1 "$URL/" && break
    sleep 1
  done
  info "Dashboard: $URL  (als Lesezeichen speichern)"
  open_browser
  exit 0
fi

# --- Läuft FasTI schon (z. B. per Autostart)? ------------------------------------
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if [ "$HEADLESS" -eq 0 ] && curl -s --max-time 2 "$URL/api/decisions" >/dev/null 2>&1; then
    info "FasTI läuft bereits im Hintergrund – öffne das Dashboard."
    open_browser
    exit 0
  fi
  fail "Port $PORT ist belegt. Anderen Port wählen:  bash start.sh --port 8080"
fi

# --- Lokale KI (Ollama): App starten, falls installiert, und Modell einmalig laden
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

# Mac nicht einschlafen lassen, solange FasTI läuft (Bildschirm darf aus)
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w $$ &
fi

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
if [ "$HEADLESS" -eq 0 ]; then
  tail -n 0 -f backend.log &   # Fortschritt im Terminal mitlesen
  TAIL_PID=$!
fi

# --- 3. Webserver ----------------------------------------------------------------
# Eigener Server: nur an localhost gebunden, liefert ausschließlich Dashboard und Lagedaten.
"$PY" server.py --port "$PORT" >>server.log 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  if curl -s -o /dev/null "$URL/"; then break; fi
  kill -0 "$SERVER_PID" 2>/dev/null || fail "Webserver konnte nicht starten (siehe server.log)."
  sleep 0.1
done

# --- 4. Browser ------------------------------------------------------------------
info "Dashboard läuft auf ${URL}  ${c_dim}(Strg+C zum Beenden)${c_off}"
TOPIC=$("$PY" -c 'import backend; print(backend.ntfy_topic())' 2>/dev/null || true)
[ -n "$TOPIC" ] && info "Push aufs iPhone: App „ntfy“ → + → Thema ${TOPIC}"
[ "$HEADLESS" -eq 0 ] && open_browser

wait "$SERVER_PID"
