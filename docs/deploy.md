# Deploy

Production runs on a Debian host as a systemd service (`deploy/install.sh`
renders `deploy/deye-inverter.service` for the folder and user it runs from).
Machine-specific values (host, folders) are in the private `opts/` repository:
`opts/README.md` and `opts/linux/config.toml`.

From the project folder on the development machine:

1. Commit and test (`pytest`, `ruff`, `mypy`).
2. Copy the committed code and the opts repository to the host's application
   folder:

   ```bash
   git archive HEAD | ssh <user>@<host> 'tar x -C <app-dir>'
   (cd opts && git archive --prefix=opts/ HEAD) | ssh <user>@<host> 'tar x -C <app-dir>'
   ```

3. On the host, in `<app-dir>`: `bash deploy/install.sh` (creates `.venv`,
   installs the package, sets `opts/` to 700 and the credentials file to 600
   again, since the copy resets file modes, installs the systemd unit if it is
   new or changed, and restarts the service).

**sudo.** The host lets the service user run only `systemctl restart` and
`systemctl is-active` for this service without a password. A routine deploy
needs nothing more. When the systemd unit is new or changed, `install.sh` needs
the sudo password: it asks for it in a terminal, or reads it once from stdin
when piped, for example from the macOS Keychain (the password never appears on
screen or in a file):

```bash
security find-generic-password -a sudo -s <keychain-service> -w \
  | ssh <user>@<host> 'bash <app-dir>/deploy/install.sh'
```

The database lives where `[storage] database` points; it survives redeploys.
Logs: `journalctl -u deye-inverter`.
