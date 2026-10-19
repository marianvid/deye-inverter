"""SQLite persistence: one database file, one repository class per kind of data."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from deye_inverter.domain.energy import DailyEnergy, EnergyBalance
from deye_inverter.domain.forecast import Forecast, ForecastHour
from deye_inverter.domain.readings import Reading
from deye_inverter.domain.settings import PlannerSettings, SettingsCodec
from deye_inverter.ports import (
    DailyEnergyRepository,
    ForecastRepository,
    JournalRepository,
    KeyValueStore,
    ReadingRepository,
    SettingsRepository,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    taken_at TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS readings_day ON readings(day);
CREATE TABLE IF NOT EXISTS forecast_hours (
    hour_end TEXT PRIMARY KEY,
    irradiance REAL NOT NULL,
    solar_kwh REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    temperature REAL
);
CREATE TABLE IF NOT EXISTS key_values (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    entry TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_kind_at ON journal(kind, at);
CREATE TABLE IF NOT EXISTS daily_energy (
    day TEXT PRIMARY KEY,
    solar REAL NOT NULL,
    consumption REAL NOT NULL,
    bought REAL NOT NULL,
    charged REAL NOT NULL,
    discharged REAL NOT NULL,
    source TEXT NOT NULL
);
"""

# Columns added after the first release: (table, column, type).
ADDED_COLUMNS = [("forecast_hours", "temperature", "REAL")]

READING_FIELDS = [f.name for f in fields(Reading) if f.name not in ("taken_at", "raw")]


class Database:
    """Owns the SQLite connection; thread-safe for the web server and scheduler."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self.transaction() as cursor:
            cursor.executescript(SCHEMA)
            self._add_missing_columns(cursor)

    @staticmethod
    def _add_missing_columns(cursor: sqlite3.Cursor) -> None:
        """Adds the columns later versions introduced to tables an older version created."""
        for table, column, kind in ADDED_COLUMNS:
            present = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
            if column not in present:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Yields a cursor under the lock; commits on success and rolls back on an exception."""
        with self._lock, self._connection:
            yield self._connection.cursor()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class SqliteReadingRepository(ReadingRepository):
    """Inverter readings in the ``readings`` table, keyed by UTC time and filed by local day."""

    def __init__(self, database: Database, timezone: Any) -> None:
        self._db = database
        self._zone = timezone

    def add(self, reading: Reading) -> None:
        """Stores one reading, replacing any reading taken at the same moment."""
        self.add_many([reading])

    def add_many(self, readings: list[Reading]) -> None:
        """Stores readings in one transaction, replacing any taken at the same moments."""
        rows = [self._row(reading) for reading in readings]
        with self._db.transaction() as cursor:
            cursor.executemany(
                "INSERT OR REPLACE INTO readings(taken_at, day, data) VALUES (?, ?, ?)", rows
            )

    def _row(self, reading: Reading) -> tuple[str, str, str]:
        payload: dict[str, Any] = {name: getattr(reading, name) for name in READING_FIELDS}
        payload["raw"] = reading.raw
        day = reading.taken_at.astimezone(self._zone).date().isoformat()
        return _iso(reading.taken_at), day, json.dumps(payload)

    def latest(self) -> Reading | None:
        """Returns the most recent stored reading, or None when there is none."""
        with self._db.transaction() as cursor:
            row = cursor.execute(
                "SELECT taken_at, data FROM readings ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
        return self._reading(row) if row else None

    def between(self, start: datetime, end: datetime) -> list[Reading]:
        """Returns readings taken from ``start`` up to, not including, ``end``, oldest first."""
        with self._db.transaction() as cursor:
            rows = cursor.execute(
                "SELECT taken_at, data FROM readings WHERE taken_at >= ? AND taken_at < ? "
                "ORDER BY taken_at",
                (_iso(start), _iso(end)),
            ).fetchall()
        return [self._reading(row) for row in rows]

    def samples_per_day(self, start: date, end: date) -> dict[date, int]:
        """Counts stored readings per local day from ``start`` to ``end``, both inclusive."""
        with self._db.transaction() as cursor:
            rows = cursor.execute(
                "SELECT day, COUNT(*) AS n FROM readings WHERE day >= ? AND day <= ? GROUP BY day",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return {date.fromisoformat(row["day"]): int(row["n"]) for row in rows}

    @staticmethod
    def _reading(row: sqlite3.Row) -> Reading:
        data = json.loads(row["data"])
        raw = data.pop("raw", {})
        known = {name: data[name] for name in READING_FIELDS if name in data}
        return Reading(taken_at=datetime.fromisoformat(row["taken_at"]), raw=raw, **known)


class SqliteForecastRepository(ForecastRepository):
    """Hourly solar forecasts in the ``forecast_hours`` table, one row per hour end."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, forecast: Forecast, fetched_at: datetime) -> None:
        """Stores each forecast hour (solar and temperature) with its fetch time, overwriting older
        forecasts for it."""
        rows = [
            (_iso(h.hour_end), h.irradiance, h.solar_kwh, _iso(fetched_at), h.temperature)
            for h in forecast.hours
        ]
        with self._db.transaction() as cursor:
            cursor.executemany(
                "INSERT OR REPLACE INTO forecast_hours"
                "(hour_end, irradiance, solar_kwh, fetched_at, temperature) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def load(self, start: datetime, end: datetime) -> Forecast:
        """Returns the stored forecast hours ending after ``start`` and up to ``end``."""
        with self._db.transaction() as cursor:
            rows = cursor.execute(
                "SELECT hour_end, irradiance, solar_kwh, temperature FROM forecast_hours "
                "WHERE hour_end > ? AND hour_end <= ? ORDER BY hour_end",
                (_iso(start), _iso(end)),
            ).fetchall()
        return Forecast.of(
            ForecastHour(
                datetime.fromisoformat(r["hour_end"]),
                r["irradiance"],
                r["solar_kwh"],
                r["temperature"],
            )
            for r in rows
        )


class SqliteKeyValueStore(KeyValueStore):
    """Named text values in the ``key_values`` table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, key: str) -> str | None:
        """Returns the value stored under ``key``, or None when it was never set."""
        with self._db.transaction() as cursor:
            row = cursor.execute("SELECT value FROM key_values WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def put(self, key: str, value: str) -> None:
        """Stores ``value`` under ``key``, replacing any previous value."""
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO key_values(key, value) VALUES (?, ?)", (key, value)
            )


class SqliteSettingsRepository(SettingsRepository):
    """Planner settings kept as one JSON value in the key-value store."""

    KEY = "planner_settings"

    def __init__(self, store: KeyValueStore, codec: SettingsCodec | None = None) -> None:
        self._store = store
        self.codec = codec or SettingsCodec()

    def load(self) -> PlannerSettings:
        """Returns the saved planner settings, or the codec's defaults when none are saved."""
        stored = self._store.get(self.KEY)
        return self.codec.from_dict(json.loads(stored)) if stored else self.codec.defaults

    def save(self, settings: PlannerSettings) -> None:
        """Encodes the planner settings as JSON and stores them, replacing the previous ones."""
        self._store.put(self.KEY, json.dumps(self.codec.to_dict(settings)))


class SqliteJournalRepository(JournalRepository):
    """Journal of planner decisions and inverter commands in the ``journal`` table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, kind: str, at: datetime, entry: dict[str, Any]) -> None:
        """Appends an entry of the given kind and time, filing its ``status`` for counting."""
        status = str(entry.get("status", ""))
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO journal(kind, at, status, entry) VALUES (?, ?, ?, ?)",
                (kind, _iso(at), status, json.dumps(entry, default=str)),
            )

    def recent(self, kind: str | None, limit: int) -> list[dict[str, Any]]:
        """Returns up to ``limit`` newest entries, of one kind or of all kinds, newest first."""
        query = "SELECT kind, at, entry FROM journal"
        params: tuple[Any, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        with self._db.transaction() as cursor:
            rows = cursor.execute(query + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
        return [{"kind": r["kind"], "at": r["at"], **json.loads(r["entry"])} for r in rows]

    def count_since(self, kind: str, since: datetime, status: str) -> int:
        """Counts entries of ``kind`` with ``status`` recorded at or after ``since``."""
        with self._db.transaction() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS n FROM journal WHERE kind = ? AND at >= ? AND status = ?",
                (kind, _iso(since), status),
            ).fetchone()
        return int(row["n"])


class SqliteDailyEnergyRepository(DailyEnergyRepository):
    """Daily energy totals (solar, consumption, bought, battery) in the ``daily_energy`` table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, record: DailyEnergy) -> None:
        """Stores one day's energy balance and its source, replacing that day's earlier record."""
        b = record.balance
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO daily_energy"
                "(day, solar, consumption, bought, charged, discharged, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.day.isoformat(),
                    b.solar,
                    b.consumption,
                    b.bought,
                    b.charged,
                    b.discharged,
                    record.source,
                ),
            )

    def between(self, start: date, end: date) -> list[DailyEnergy]:
        """Returns the daily energy records from ``start`` to ``end``, both inclusive, by day."""
        with self._db.transaction() as cursor:
            rows = cursor.execute(
                "SELECT * FROM daily_energy WHERE day >= ? AND day <= ? ORDER BY day",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [self._record(row) for row in rows]

    def first_day(self) -> date | None:
        """Returns the earliest day with a stored energy record, or None when there is none."""
        with self._db.transaction() as cursor:
            row = cursor.execute("SELECT MIN(day) AS first FROM daily_energy").fetchone()
        return date.fromisoformat(row["first"]) if row["first"] else None

    @staticmethod
    def _record(row: sqlite3.Row) -> DailyEnergy:
        balance = EnergyBalance(
            solar=row["solar"],
            consumption=row["consumption"],
            bought=row["bought"],
            charged=row["charged"],
            discharged=row["discharged"],
        )
        return DailyEnergy(date.fromisoformat(row["day"]), balance, row["source"])
