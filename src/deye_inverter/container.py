"""Composition root: builds every object from the configuration."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from deye_inverter.adapters.clock import SystemClock
from deye_inverter.adapters.deye_cloud import DeyeCloudClient, DeyeCloudGateway
from deye_inverter.adapters.deye_cloud_history import DeyeCloudHistory
from deye_inverter.adapters.open_meteo import OpenMeteoForecast
from deye_inverter.adapters.sqlite_store import (
    Database,
    SqliteDailyEnergyRepository,
    SqliteForecastRepository,
    SqliteJournalRepository,
    SqliteKeyValueStore,
    SqliteReadingRepository,
    SqliteSettingsRepository,
)
from deye_inverter.application.auth import PasswordService
from deye_inverter.application.charge_service import ChargeSettingsService
from deye_inverter.application.collection import (
    CollectReadings,
    RefreshForecast,
    RefreshInverterSettings,
)
from deye_inverter.application.energy_model import EnergyModel
from deye_inverter.application.history_sync import BackfillFrames, RecordToday, SyncDailyEnergy
from deye_inverter.application.inverter_state import InverterState
from deye_inverter.application.manual_charge import (
    ManualChargeDependencies,
    ManualChargeRepository,
    ManualChargeService,
)
from deye_inverter.application.planner_service import PlannerDependencies, PlannerService
from deye_inverter.application.profiles import ProfileService
from deye_inverter.application.scheduler import JobChain, JobScheduler
from deye_inverter.application.statistics import StatisticsViews
from deye_inverter.application.time_of_use_service import TimeOfUseService
from deye_inverter.application.views import DashboardViews
from deye_inverter.config import AppConfig, CredentialsReader, IntervalsConfig
from deye_inverter.domain.settings import PlannerSettings, SettingsCodec, SiteSettings
from deye_inverter.ports import (
    Clock,
    EnergyHistorySource,
    ForecastProvider,
    InverterGateway,
    JournalRepository,
    SettingsRepository,
)


@dataclass
class Services:
    """Everything the web layer and the scheduler use."""

    clock: Clock
    state: InverterState
    settings: SettingsRepository
    journal: JournalRepository
    passwords: PasswordService
    views: DashboardViews
    statistics: StatisticsViews
    time_of_use: TimeOfUseService
    planner: PlannerService
    charging: ChargeSettingsService
    manual: ManualChargeService
    profiles: ProfileService
    collect_readings: CollectReadings
    refresh_inverter: RefreshInverterSettings
    refresh_forecast: RefreshForecast
    record_today: RecordToday
    sync_daily: SyncDailyEnergy
    backfill: BackfillFrames
    scheduler: JobScheduler | None = None


@dataclass(frozen=True)
class Outside:
    """The outside systems the application talks to (each behind its port)."""

    gateway: InverterGateway
    forecast: ForecastProvider
    history: EnergyHistorySource
    clock: Clock
    timezone: str
    sleep: Callable[[float], None] = time.sleep
    site: SiteSettings = field(default_factory=SiteSettings)


@dataclass(frozen=True)
class Storage:
    """Repositories over one database."""

    store: SqliteKeyValueStore
    readings: SqliteReadingRepository
    forecasts: SqliteForecastRepository
    settings: SqliteSettingsRepository
    journal: SqliteJournalRepository
    daily: SqliteDailyEnergyRepository
    state: InverterState
    charges: ManualChargeRepository

    @classmethod
    def open(cls, database: Database, outside: Outside) -> Storage:
        store = SqliteKeyValueStore(database)
        codec = SettingsCodec(PlannerSettings(site=outside.site))
        return cls(
            store=store,
            readings=SqliteReadingRepository(database, ZoneInfo(outside.timezone)),
            forecasts=SqliteForecastRepository(database),
            settings=SqliteSettingsRepository(store, codec),
            journal=SqliteJournalRepository(database),
            daily=SqliteDailyEnergyRepository(database),
            state=InverterState(store),
            charges=ManualChargeRepository(store),
        )


def build_services(database: Database, outside: Outside) -> Services:
    db = Storage.open(database, outside)
    clock = outside.clock
    commands = TimeOfUseService(
        outside.gateway, db.state, db.journal, clock, db.settings, outside.sleep
    )
    refresh_forecast = RefreshForecast(outside.forecast, db.forecasts, db.settings, clock)
    charging = ChargeSettingsService(outside.gateway, db.state, db.journal, clock)
    planner = _planner(db, commands, refresh_forecast, clock)
    return Services(
        clock=clock,
        state=db.state,
        settings=db.settings,
        journal=db.journal,
        passwords=PasswordService(db.store),
        views=DashboardViews(db.readings, db.forecasts, db.daily, db.state, clock),
        statistics=StatisticsViews(db.daily, db.readings, clock),
        time_of_use=commands,
        planner=planner,
        charging=charging,
        manual=ManualChargeService(
            ManualChargeDependencies(
                db.charges, db.settings, planner, charging, db.state, db.readings, db.journal, clock
            )
        ),
        profiles=ProfileService(db.store, db.settings, commands),
        collect_readings=CollectReadings(outside.gateway, db.readings),
        refresh_inverter=RefreshInverterSettings(outside.gateway, db.state, clock),
        refresh_forecast=refresh_forecast,
        record_today=RecordToday(db.readings, db.daily, clock),
        sync_daily=SyncDailyEnergy(outside.history, db.daily, clock),
        backfill=BackfillFrames(outside.history, db.readings, clock),
    )


def _planner(
    db: Storage, commands: TimeOfUseService, refresh_forecast: RefreshForecast, clock: Clock
) -> PlannerService:
    return PlannerService(
        PlannerDependencies(
            settings=db.settings,
            state=db.state,
            readings=db.readings,
            forecasts=db.forecasts,
            energy=EnergyModel(db.readings),
            commands=commands,
            journal=db.journal,
            clock=clock,
            refresh_forecast=refresh_forecast,
            manual_charge=db.charges.current,
        )
    )


def build_from_config(config: AppConfig) -> Services:
    clock = SystemClock(config.site.timezone)
    credentials = CredentialsReader().read(config.deye.credentials_file)
    client = DeyeCloudClient(config.deye.base_url, credentials)
    outside = Outside(
        gateway=DeyeCloudGateway(client, config.deye.device_sn),
        forecast=OpenMeteoForecast(config.site.timezone),
        history=DeyeCloudHistory(client, config.site.timezone),
        clock=clock,
        timezone=config.site.timezone,
        site=SiteSettings(latitude=config.site.latitude, longitude=config.site.longitude),
    )
    services = build_services(Database(config.storage.database), outside)
    services.scheduler = build_scheduler(services, config.site.timezone, config.intervals)
    return services


def build_scheduler(services: Services, timezone: str, intervals: IntervalsConfig) -> JobScheduler:
    scheduler = JobScheduler(timezone, services.journal, services.clock)
    scheduler.add_interval(
        "readings",
        JobChain(services.collect_readings, services.record_today, services.manual.tick),
        intervals.readings_minutes,
    )
    scheduler.add_interval("daily-energy", services.sync_daily, intervals.daily_energy_minutes)
    scheduler.add_interval("history-backfill", services.backfill, intervals.backfill_minutes)
    scheduler.add_interval(
        "inverter-settings", services.refresh_inverter, intervals.inverter_settings_minutes
    )
    scheduler.add_interval("forecast", services.refresh_forecast, intervals.forecast_minutes)
    scheduler.schedule_planner(services.settings.load(), services.planner.run)
    return scheduler
