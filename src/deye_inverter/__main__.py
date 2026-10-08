"""Command line: ``python -m deye_inverter serve``."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from deye_inverter.config import ConfigLoader
from deye_inverter.container import build_from_config
from deye_inverter.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="deye-inverter")
    parser.add_argument("command", choices=["serve"], help="serve: web interface and jobs")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = ConfigLoader().load()
    app = create_app(build_from_config(config))
    uvicorn.run(app, host=config.web.host, port=config.web.port, log_level="info")


if __name__ == "__main__":
    main()
