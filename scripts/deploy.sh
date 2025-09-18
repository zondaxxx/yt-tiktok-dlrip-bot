#!/usr/bin/env bash
set -euo pipefail

# Ultra-simple one-shot deploy script for the bot.
# Does: install deps, create venv, install requirements, create .env, optional session generate,
# write systemd unit, start service, and helpers for logs/update.

SERVICE_NAME=${SERVICE_NAME:-yt-dlp-bot}
PYTHON_BIN=${PYTHON_BIN:-python3}
VENVDIR=${VENVDIR:-.venv}
WORKDIR=${WORKDIR:-$(pwd)}
RUN_USER=${RUN_USER:-$(id -un)}
SYSTEMD_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

info() { echo -e "\033[1;34m[+]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
err()  { echo -e "\033[1;31m[x]\033[0m $*" >&2; }

ensure_deps() {
  info "Ensuring system packages (python3, venv, pip, ffmpeg, git)"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip ffmpeg git
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip python3-virtualenv ffmpeg git || true
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3 python3-pip python3-virtualenv ffmpeg git || true
  else
    warn "Unknown package manager. Please install: python3, python3-venv, python3-pip, ffmpeg, git"
  fi
}

ensure_venv() {
  info "Creating venv at ${VENVDIR}"
  if [ ! -d "${VENVDIR}" ]; then
    ${PYTHON_BIN} -m venv "${VENVDIR}"
  fi
  # shellcheck disable=SC1090
  source "${VENVDIR}/bin/activate"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
}

prompt_env() {
  info "Preparing .env"
  local env_file=.env
  if [ ! -f "$env_file" ]; then
    cp .env.example "$env_file" || true
  fi
  # Read current values if exist
  local BOT_TOKEN TG_API_ID TG_API_HASH TG_SESSION_STRING BYPASS_MODE
  BOT_TOKEN=$(grep -E '^BOT_TOKEN=' "$env_file" 2>/dev/null | sed 's/^BOT_TOKEN=//') || true
  TG_API_ID=$(grep -E '^TG_API_ID=' "$env_file" 2>/dev/null | sed 's/^TG_API_ID=//') || true
  TG_API_HASH=$(grep -E '^TG_API_HASH=' "$env_file" 2>/dev/null | sed 's/^TG_API_HASH=//') || true
  TG_SESSION_STRING=$(grep -E '^TG_SESSION_STRING=' "$env_file" 2>/dev/null | sed 's/^TG_SESSION_STRING=//') || true
  BYPASS_MODE=$(grep -E '^BYPASS_MODE=' "$env_file" 2>/dev/null | sed 's/^BYPASS_MODE=//') || true

  read -r -p "BOT_TOKEN [${BOT_TOKEN:-none}]: " _in || true
  BOT_TOKEN=${_in:-$BOT_TOKEN}
  read -r -p "BYPASS_MODE (off/userbot) [${BYPASS_MODE:-userbot}]: " _in || true
  BYPASS_MODE=${_in:-${BYPASS_MODE:-userbot}}
  read -r -p "TG_API_ID [${TG_API_ID:-none}]: " _in || true
  TG_API_ID=${_in:-$TG_API_ID}
  read -r -p "TG_API_HASH [${TG_API_HASH:-none}]: " _in || true
  TG_API_HASH=${_in:-$TG_API_HASH}

  if [ -z "${TG_SESSION_STRING:-}" ]; then
    read -r -p "Generate TG_SESSION_STRING now? (y/N): " gen || true
    if [[ "${gen,,}" =~ ^y ]]; then
      read -r -p "Your phone in intl format (+7999...): " TG_PHONE || true
      TG_PHONE=${TG_PHONE:-""}
      info "Generating session (will prompt code/2FA)…"
      # shellcheck disable=SC1090
      source "${VENVDIR}/bin/activate"
      TG_API_ID="$TG_API_ID" TG_API_HASH="$TG_API_HASH" TG_PHONE="$TG_PHONE" WRITE_ENV=1 \
        python -m tools.gen_session_for_number || warn "Session generation failed; you can fill later"
      # Reload updated value if written
      TG_SESSION_STRING=$(grep -E '^TG_SESSION_STRING=' "$env_file" 2>/dev/null | sed 's/^TG_SESSION_STRING=//') || true
    fi
  fi

  # Write back
  {
    echo "BOT_TOKEN=${BOT_TOKEN}"
    echo "BYPASS_MODE=${BYPASS_MODE}"
    echo "TG_API_ID=${TG_API_ID}"
    echo "TG_API_HASH=${TG_API_HASH}"
    echo "TG_SESSION_STRING=${TG_SESSION_STRING}"
  } > "$env_file"
  info ".env saved"
}

write_service() {
  info "Writing systemd service to ${SYSTEMD_FILE} (user=${RUN_USER})"
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
  info "Enabling and starting ${SERVICE_NAME}"
  sudo systemctl enable "${SERVICE_NAME}" || true
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true
}

git_update_if_any() {
  if [ -d .git ]; then
    info "Pulling latest changes"
    git pull --ff-only || warn "git pull failed"
  fi
}

case "${1:-install}" in
  install)
    ensure_deps
    ensure_venv
    prompt_env
    write_service
    start_service
    ;;
  update)
    git_update_if_any
    ensure_venv
    start_service
    ;;
  session)
    # Re-generate session string only
    ensure_venv
    read -r -p "Phone (+7999…): " TG_PHONE || true
    source "${VENVDIR}/bin/activate"
    TG_PHONE="$TG_PHONE" WRITE_ENV=1 python -m tools.gen_session_for_number || true
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
  uninstall)
    warn "Stopping and disabling ${SERVICE_NAME}"
    sudo systemctl stop "${SERVICE_NAME}" || true
    sudo systemctl disable "${SERVICE_NAME}" || true
    sudo rm -f "${SYSTEMD_FILE}" || true
    sudo systemctl daemon-reload || true
    info "Removed systemd unit"
    ;;
  *)
    echo "Usage: $0 {install|update|session|restart|stop|start|status|logs|uninstall}" >&2
    exit 1
    ;;
esac
