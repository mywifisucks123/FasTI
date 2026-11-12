#!/usr/bin/env bash
# =============================================================================
# FasTI – Einrichtung als Dauerdienst auf einem Ubuntu/Debian-Homeserver
#
#   bash install-server.sh             installieren bzw. aktualisieren und starten
#   bash install-server.sh --ohne-ki   ohne lokale KI (nur regelbasiert, spart RAM/CPU)
#   bash install-server.sh --status    läuft FasTI? letzte Log-Zeilen
#   bash install-server.sh --entfernen Dienst stoppen und entfernen (Daten bleiben)
#
# Danach startet FasTI mit dem Server, läuft rund um die Uhr und startet sich nach
# Abstürzen selbst neu. Dashboard im Heimnetz: http://<Server-IP>:8000
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
PORT="${PORT:-8000}"
SERVICE="fasti"
UNIT="/etc/systemd/system/${SERVICE}.service"
WITH_AI=1
MODE="install"

for arg in "$@"; do
  case "$arg" in
    --ohne-ki)   WITH_AI=0 ;;
    --status)    MODE="status" ;;
    --entfernen) MODE="remove" ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $arg"; exit 1 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
info() { printf '%s▸%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s▸ %s%s\n' "$c_ylw" "$*" "$c_off"; }
fail() { printf '%s✗ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || fail "Dieses Skript ist für den Linux-Homeserver. Auf dem Mac: bash start.sh"
command -v systemctl >/dev/null 2>&1 || fail "systemd nicht gefunden – dieses Skript braucht Ubuntu/Debian mit systemd."
[ "$(id -u)" -ne 0 ] || fail "Bitte als normaler Benutzer starten (nicht mit sudo). Das Skript fragt selbst nach dem Passwort."
RUN_USER="$(id -un)"

# --- Status -----------------------------------------------------------------------
if [ "$MODE" = "status" ]; then
  systemctl --no-pager --lines=0 status "$SERVICE" || true
  echo
  info "Letzte Zeilen aus backend.log:"
  tail -n 15 backend.log 2>/dev/null || echo "(noch kein Log)"
  exit 0
fi

# --- Entfernen ----------------------------------------------------------------------
if [ "$MODE" = "remove" ]; then
  sudo systemctl disable --now "$SERVICE" 2>/dev/null || true
  sudo rm -f "$UNIT"
  sudo systemctl daemon-reload
  info "FasTI-Dienst entfernt. Dateien und Daten in $APP_DIR bleiben erhalten."
  exit 0
fi

info "Richte FasTI in $APP_DIR für Benutzer $RUN_USER ein …"
sudo -v || fail "Ohne sudo-Rechte geht es nicht."

# --- 1. Systempakete ------------------------------------------------------------------
NEED=()
command -v python3 >/dev/null 2>&1 || NEED+=(python3)
python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || NEED+=(python3-venv)
command -v curl >/dev/null 2>&1 || NEED+=(curl)
command -v lsof >/dev/null 2>&1 || NEED+=(lsof)
if [ "${#NEED[@]}" -gt 0 ]; then
  info "Installiere Systempakete: ${NEED[*]}"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${NEED[@]}"
fi

# Eine vom Mac mitkopierte .venv funktioniert unter Linux nicht → neu anlegen
if [ -d .venv ] && ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  info "Entferne die vom Mac mitkopierte Python-Umgebung …"
  rm -rf .venv
fi

# --- 2. Lokale KI (Ollama) ------------------------------------------------------------
if [ "$WITH_AI" -eq 1 ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    info "Installiere Ollama (lokale KI, offizielles Installationsskript von ollama.com) …"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  # Ollama sparsam betreiben: ein Modell, eine Anfrage gleichzeitig, niedrige Priorität,
  # damit VMs und andere Dienste auf dem Server Vorrang behalten.
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  sudo tee /etc/systemd/system/ollama.service.d/fasti.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Nice=10
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now ollama >/dev/null 2>&1 || true
  sudo systemctl restart ollama || true
  for _ in $(seq 1 30); do
    curl -s -o /dev/null --max-time 2 http://localhost:11434/api/tags && break
    sleep 1
  done
else
  warn "Ohne lokale KI: Meldungen werden regelbasiert bewertet."
fi

# --- 3. Python-Umgebung und KI-Modell (über start.sh) -----------------------------------
SETUP_ARGS="--setup-only"
[ "$WITH_AI" -eq 0 ] && SETUP_ARGS="--setup-only --no-ai"
# shellcheck disable=SC2086
bash start.sh $SETUP_ARGS

# --- 4. Dauerdienst ---------------------------------------------------------------------
EXTRA=""
[ "$WITH_AI" -eq 0 ] && EXTRA=" --no-ai"
AFTER="network-online.target"
[ "$WITH_AI" -eq 1 ] && AFTER="network-online.target ollama.service"
info "Richte den Dienst ein (startet automatisch mit dem Server) …"
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=FasTI Threat & Crisis Intelligence
After=$AFTER
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/start.sh --headless --bind 0.0.0.0 --port $PORT$EXTRA
Restart=always
RestartSec=30
Nice=10
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null 2>&1
sudo systemctl restart "$SERVICE"

# --- 5. Firewall (nur falls ufw aktiv ist): Port fürs Heimnetz öffnen --------------------
if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  SUBNET=$(ip -o -f inet addr show scope global 2>/dev/null | awk '{print $4}' | head -n1 \
           | python3 -c 'import sys, ipaddress; print(ipaddress.ip_interface(sys.stdin.read().strip()).network)' 2>/dev/null || true)
  if [ -n "$SUBNET" ]; then
    sudo ufw allow from "$SUBNET" to any port "$PORT" proto tcp >/dev/null
    info "Firewall: Port $PORT für das Heimnetz $SUBNET freigegeben."
  fi
fi

# --- 6. Kontrolle -----------------------------------------------------------------------
for _ in $(seq 1 60); do
  curl -s -o /dev/null --max-time 2 "http://localhost:$PORT/" && break
  sleep 1
done
if curl -s -o /dev/null --max-time 2 "http://localhost:$PORT/"; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  TOPIC=$(.venv/bin/python -c 'import backend; print(backend.ntfy_topic())' 2>/dev/null || true)
  echo
  info "FasTI läuft als Dauerdienst."
  info "Dashboard im Heimnetz:  http://${LAN_IP:-<Server-IP>}:$PORT   (auf Mac und iPhone als Lesezeichen speichern)"
  [ -n "$TOPIC" ] && info "Push-Thema (ntfy):     $TOPIC"
  info "Status und Log:        bash install-server.sh --status"
  info "Der erste Durchlauf mit lokaler KI dauert auf diesem Rechner bis zu 20 Minuten; das Dashboard füllt sich nach und nach."
else
  warn "Der Dienst antwortet noch nicht. Prüfen mit:  bash install-server.sh --status"
fi
