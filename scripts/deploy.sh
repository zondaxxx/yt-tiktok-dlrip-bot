#!/usr/bin/env bash
set -euo pipefail

# Telegram Video Downloader Bot deployment script
# Usage:
#   ./scripts/deploy.sh install   # Install deps, venv, systemd service and start
#   ./scripts/deploy.sh update    # Reinstall deps and restart
#   ./scripts/deploy.sh restart   # Restart the service
#   ./scripts/deploy.sh stop      # Stop the service
#   ./scripts/deploy.sh start     # Start the service
#   ./scripts/deploy.sh status    # Service status
#   ./scripts/deploy.sh logs      # Follow logs

SERVICE_NAME=${SERVICE_NAME:-yt-dlp-bot}
PYTHON_BIN=${PYTHON_BIN:-python3}
VENVDIR=${VENVDIR:-.venv}
WORKDIR=${WORKDIR:-$(pwd)}
RUN_USER=${RUN_USER:-$(id -un)}

SYSTEMD_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

ensure_deps() {
  echo "[+] Ensuring system packages (python3, venv, ffmpeg)"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip python3-virtualenv ffmpeg || true
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3 python3-pip python3-virtualenv ffmpeg || true
  else
    echo "[!] Unknown package manager. Please install: python3, python3-venv, python3-pip, ffmpeg" >&2
  fi
}

ensure_venv() {
  echo "[+] Creating venv at ${VENVDIR}"
  if [ ! -d "${VENVDIR}" ]; then
    ${PYTHON_BIN} -m venv "${VENVDIR}"
  fi
  # shellcheck disable=SC1090
  source "${VENVDIR}/bin/activate"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
}

write_service() {
  echo "[+] Writing systemd service to ${SYSTEMD_FILE} (user=${RUN_USER})"
  tmpfile=$(mktemp)
  cat >"${tmpfile}" <<EOF
[Unit]
Description=YT/TikTok Downloader Bot (aiogram + yt-dlp)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${WORKDIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${WORKDIR}/${VENVDIR}/bin/python -m app.main
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo mv "${tmpfile}" "${SYSTEMD_FILE}"
  sudo chmod 0644 "${SYSTEMD_FILE}"
  sudo systemctl daemon-reload
}

start_service() {
  echo "[+] Enabling and starting ${SERVICE_NAME}"
  sudo systemctl enable "${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true
}

case "${1:-install}" in
  install)
    ensure_deps
    ensure_venv
    if [ ! -f .env ]; then
      echo "[!] .env not found, copying from .env.example"
      cp .env.example .env || true
      echo "[!] Edit .env before starting the service (BOT_TOKEN, TG_* vars)."
    fi
    write_service
    start_service
    ;;
  update)
    ensure_venv
    start_service
    ;;
  restart)
    sudo systemctl restart "${SERVICE_NAME}"
    ;;
  stop)
    sudo systemctl stop "${SERVICE_NAME}"
    ;;
  start)
    sudo systemctl start "${SERVICE_NAME}"
    ;;
  status)
    sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true
    ;;
  logs)
    sudo journalctl -u "${SERVICE_NAME}" -f -n 200
    ;;
  *)
    echo "Usage: $0 {install|update|restart|stop|start|status|logs}" >&2
    exit 1
    ;;
esac

