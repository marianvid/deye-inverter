# 0010 — Deploy with the least sudo

Date: 2026-10-18 · Status: accepted

**Context.** Home-lab security rules: one sudo password, no blanket passwordless sudo.
The application itself never needs root.

**Decision.** The service runs as an ordinary user. The host allows only
`systemctl restart` and `systemctl is-active` for this service without a password.
`install.sh` installs the systemd unit only when it is new or changed, with the sudo
password typed or read once from stdin (for example from the Keychain).

**Consequences.** A routine deploy needs no password; changing the unit, which is
root-level, always does.
