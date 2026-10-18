"""Named Time of Use tables that can be sent to the inverter in one step."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from deye_inverter.application.time_of_use_service import CommandOutcome, TimeOfUseService
from deye_inverter.domain.settings import Mode
from deye_inverter.domain.time_of_use import TimeOfUseTable, table_from_dicts, table_to_dicts
from deye_inverter.ports import KeyValueStore, SettingsRepository

PROFILES = "time_of_use_profiles"
MAX_NAME_LENGTH = 40


class ProfileError(ValueError):
    """A profile name is empty, too long or unknown."""


class ProfilesLockedError(ProfileError):
    """Profiles can be sent only while the automation is off."""


@dataclass(frozen=True)
class Profile:
    """A time-of-use table saved under a name."""

    name: str
    table: TimeOfUseTable

    def as_dict(self) -> dict[str, Any]:
        """The profile as a JSON-ready dict: its name and its table's slots."""
        return {"name": self.name, "slots": table_to_dicts(self.table)}


class ProfileService:
    """Saves, lists and deletes named time-of-use tables and sends one to the inverter while the
    automation is off."""

    def __init__(
        self, store: KeyValueStore, settings: SettingsRepository, commands: TimeOfUseService
    ) -> None:
        self._store = store
        self._settings = settings
        self._commands = commands

    def all(self) -> list[Profile]:
        """Every saved profile, sorted by name."""
        raw = self._store.get(PROFILES)
        items = json.loads(raw) if raw else []
        return [Profile(i["name"], table_from_dicts(i["slots"])) for i in items]

    def save(self, name: str, table: TimeOfUseTable) -> list[Profile]:
        """Saves the table under the trimmed name (1 to 40 characters), replacing a profile of that
        name; returns all profiles."""
        clean = name.strip()
        if not clean or len(clean) > MAX_NAME_LENGTH:
            raise ProfileError(f"A profile name needs 1 to {MAX_NAME_LENGTH} characters")
        profiles = [p for p in self.all() if p.name != clean] + [Profile(clean, table)]
        self._write(sorted(profiles, key=lambda p: p.name.lower()))
        return self.all()

    def delete(self, name: str) -> list[Profile]:
        """Removes the named profile; returns the remaining profiles."""
        self._write([p for p in self.all() if p.name != name])
        return self.all()

    def apply(self, name: str) -> CommandOutcome:
        """Sends the named profile's table to the inverter; refused unless the automation is off."""
        if self._settings.load().mode is not Mode.OFF:
            raise ProfilesLockedError("Switch the automation off (Plan page) to send a profile")
        profile = next((p for p in self.all() if p.name == name), None)
        if profile is None:
            raise ProfileError(f"No profile named {name}")
        return self._commands.send(profile.table, f"profile {name}")

    def _write(self, profiles: list[Profile]) -> None:
        self._store.put(PROFILES, json.dumps([p.as_dict() for p in profiles]))
