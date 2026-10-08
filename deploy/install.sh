#!/usr/bin/env bash
# Installs or updates deye-inverter on a Debian host, from the project folder
# (code plus opts/) copied there. Needs sudo for the systemd unit.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="$(id -un)"
cd "$APP_DIR"

# Copying with git archive | tar resets file modes: keep the private settings private.
if [ -d opts ]; then chmod 700 opts; fi
if [ -f opts/credentials.txt ]; then chmod 600 opts/credentials.txt; fi

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet .

sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER@|$APP_USER|g" deploy/deye-inverter.service \
  | sudo tee /etc/systemd/system/deye-inverter.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --quiet deye-inverter
sudo systemctl restart deye-inverter
systemctl --no-pager --lines=5 status deye-inverter
