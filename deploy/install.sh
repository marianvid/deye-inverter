#!/usr/bin/env bash
# Installs or updates deye-inverter on a Debian host, from the project folder
# (code plus opts/) copied there.
#
# sudo: a routine deploy only restarts the service, which the host allows without a
# password. Installing or changing the systemd unit is root-level and needs the sudo
# password: typed when run from a terminal, or read once from stdin when piped
# (for example from the Mac Keychain), never printed or stored.
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

UNIT=/etc/systemd/system/deye-inverter.service
rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER@|$APP_USER|g" deploy/deye-inverter.service >"$rendered"

if cmp -s "$rendered" "$UNIT"; then
  echo "systemd unit unchanged"
else
  echo "systemd unit new or changed: installing it (needs the sudo password)"
  password=""
  if [ ! -t 0 ]; then IFS= read -r password || true; fi
  as_root() {
    if [ -n "$password" ]; then printf '%s\n' "$password" | sudo -S -p '' "$@"; else sudo "$@"; fi
  }
  as_root install -m 0644 "$rendered" "$UNIT"
  as_root systemctl daemon-reload
  as_root systemctl enable --quiet deye-inverter
  password=""
fi

# Allowed without a password on the host (sudoers: restart and is-active only).
sudo -n systemctl restart deye-inverter
sleep 3
systemctl is-active deye-inverter
