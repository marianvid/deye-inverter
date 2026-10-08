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
   again, since the copy resets file modes, installs and restarts the service).

The database lives where `[storage] database` points; it survives redeploys.
Logs: `journalctl -u deye-inverter`.
