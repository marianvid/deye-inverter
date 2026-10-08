from pathlib import Path

import pytest

from deye_inverter.config import ConfigError, ConfigLoader, CredentialsReader


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        '[deye]\ncredentials_file = "/x/credentials.txt"\n'
        '[storage]\ndatabase = "/x/deye.db"\n[web]\nport = 9000\n',
        encoding="utf-8",
    )
    return path


def test_load_with_environment_override(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    config = ConfigLoader(
        {"DEYE_INVERTER_CONFIG": str(path), "DEYE_INVERTER_WEB_PORT": "8081"}
    ).load()
    assert config.web.port == 8081
    assert config.storage.database == Path("/x/deye.db")
    assert config.deye.base_url.startswith("https://")
    assert config.site.timezone == "Europe/Bucharest"


def test_missing_values_are_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        ConfigLoader({}).load()
    with pytest.raises(ConfigError):
        ConfigLoader({}).load(tmp_path / "nope.toml")
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigLoader({}).load(empty)


def test_credentials_reader(tmp_path: Path) -> None:
    path = tmp_path / "credentials.txt"
    path.write_text(
        "# comment\napp_id=1\napp_secret=s\nemail=a@b\npassword_sha256=abc", encoding="utf-8"
    )
    credentials = CredentialsReader().read(path)
    assert credentials.app_id == "1" and credentials.password_sha256 == "abc"
    path.write_text("app_id=1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        CredentialsReader().read(path)
    with pytest.raises(ConfigError):
        CredentialsReader().read(tmp_path / "missing.txt")


def test_site_location_and_intervals_come_from_the_configuration(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[deye]\ncredentials_file = "/x/c.txt"\n[storage]\ndatabase = "/x/d.db"\n'
        "[site]\nlatitude = 1.5\nlongitude = -2.25\n[intervals]\nreadings_minutes = 7\n",
        encoding="utf-8",
    )
    config = ConfigLoader({}).load(path)
    assert (config.site.latitude, config.site.longitude) == (1.5, -2.25)
    assert config.intervals.readings_minutes == 7
    assert config.web.host == "127.0.0.1"
