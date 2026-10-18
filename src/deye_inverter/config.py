"""Machine configuration: the one module that reads the configuration file.

Values come from a TOML file (path in ``DEYE_INVERTER_CONFIG``) and may be
overridden by environment variables named ``DEYE_INVERTER_<SECTION>_<KEY>``. Defaults live in
``defaults.toml`` beside this module, not in the code.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

ENV_PREFIX = "DEYE_INVERTER_"
CONFIG_ENV = f"{ENV_PREFIX}CONFIG"
DEFAULTS_FILE = "defaults.toml"


class ConfigError(Exception):
    """Raised when the configuration is missing or incomplete."""


@dataclass(frozen=True)
class DeyeConfig:
    """DeyeCloud API base URL, path of the credentials file and the inverter's serial number."""

    base_url: str
    credentials_file: Path
    device_sn: str


@dataclass(frozen=True)
class StorageConfig:
    """Path of the SQLite database file."""

    database: Path


@dataclass(frozen=True)
class WebConfig:
    """Host and port the web interface listens on."""

    host: str
    port: int


@dataclass(frozen=True)
class SiteConfig:
    """Where the panels are. Latitude and longitude are private (opts) and are the
    defaults of the planner's site settings until edited in the interface."""

    timezone: str
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass(frozen=True)
class ForecastConfig:
    """Where the weather forecast is asked (the Open-Meteo forecast endpoint)."""

    url: str


@dataclass(frozen=True)
class IntervalsConfig:
    """How often the background jobs run, in minutes."""

    readings_minutes: int = 5
    inverter_settings_minutes: int = 30
    forecast_minutes: int = 60
    daily_energy_minutes: int = 60
    backfill_minutes: int = 10


@dataclass(frozen=True)
class AppConfig:
    """The whole machine configuration: DeyeCloud, storage, web, site, forecast, job intervals."""

    deye: DeyeConfig
    storage: StorageConfig
    web: WebConfig
    site: SiteConfig
    forecast: ForecastConfig
    intervals: IntervalsConfig = IntervalsConfig()


@dataclass(frozen=True)
class Credentials:
    """DeyeCloud API app id and secret, account email and SHA-256 of the account password."""

    app_id: str
    app_secret: str
    email: str
    password_sha256: str


class ConfigLoader:
    """Builds an :class:`AppConfig` from a TOML file plus environment overrides."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        self._defaults = tomllib.loads(
            resources.files("deye_inverter").joinpath(DEFAULTS_FILE).read_text(encoding="utf-8")
        )

    def load(self, path: Path | None = None) -> AppConfig:
        """Reads the TOML file (default: the path in ``DEYE_INVERTER_CONFIG``) and applies
        environment overrides and defaults."""
        raw = self._read_file(path or self._path_from_env())
        return AppConfig(
            deye=DeyeConfig(
                base_url=self._value(raw, "deye", "base_url"),
                credentials_file=Path(self._required(raw, "deye", "credentials_file")),
                device_sn=self._value(raw, "deye", "device_sn", ""),
            ),
            storage=StorageConfig(database=Path(self._required(raw, "storage", "database"))),
            web=WebConfig(
                host=self._value(raw, "web", "host"),
                port=int(self._value(raw, "web", "port")),
            ),
            site=SiteConfig(
                timezone=self._value(raw, "site", "timezone"),
                latitude=float(self._value(raw, "site", "latitude", "0")),
                longitude=float(self._value(raw, "site", "longitude", "0")),
            ),
            forecast=ForecastConfig(url=self._value(raw, "forecast", "url")),
            intervals=self._intervals(raw),
        )

    def _intervals(self, raw: dict[str, Any]) -> IntervalsConfig:
        defaults = IntervalsConfig()
        values = {
            name: int(self._value(raw, "intervals", name, str(getattr(defaults, name))))
            for name in defaults.__dataclass_fields__
        }
        return IntervalsConfig(**values)

    def _path_from_env(self) -> Path:
        value = self._environ.get(CONFIG_ENV)
        if not value:
            raise ConfigError(f"Set {CONFIG_ENV} to the path of the configuration file")
        return Path(value)

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ConfigError(f"Configuration file not found: {path}")
        with path.open("rb") as handle:
            return tomllib.load(handle)

    def _value(
        self, raw: dict[str, Any], section: str, key: str, default: str | None = None
    ) -> str:
        """The value from the environment, else the machine's file, else ``default``, else
        ``defaults.toml``."""
        env_name = f"{ENV_PREFIX}{section.upper()}_{key.upper()}"
        if env_name in self._environ:
            return self._environ[env_name]
        if default is None:
            default = str(self._defaults.get(section, {}).get(key, ""))
        return str(raw.get(section, {}).get(key, default))

    def _required(self, raw: dict[str, Any], section: str, key: str) -> str:
        value = self._value(raw, section, key, "")
        if not value:
            raise ConfigError(f"Missing configuration value [{section}] {key}")
        return value


class CredentialsReader:
    """Reads the DeyeCloud credentials file (``key=value`` lines)."""

    REQUIRED = ("app_id", "app_secret", "email", "password_sha256")

    def read(self, path: Path) -> Credentials:
        """Parses the credentials file; raises :class:`ConfigError` if it is missing or lacks a
        required key."""
        if not path.is_file():
            raise ConfigError(f"Credentials file not found: {path}")
        values = self._parse(path.read_text(encoding="utf-8"))
        missing = [key for key in self.REQUIRED if not values.get(key)]
        if missing:
            raise ConfigError(f"Credentials file lacks: {', '.join(missing)}")
        return Credentials(**{key: values[key] for key in self.REQUIRED})

    @staticmethod
    def _parse(text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        return values
