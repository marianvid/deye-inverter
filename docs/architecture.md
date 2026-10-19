# Architecture

How the code is organised and why. The behaviour (what the planner decides) is in
[`planner.md`](planner.md); the agreed requirements and defaults are in
[`specification.md`](specification.md); each important decision has a short record
in [`decisions/`](decisions/).

## Layers

Ports and adapters (hexagonal architecture). Dependencies point inwards: the domain
knows nothing about the web, the database, DeyeCloud or the clock.

```
web  ──►  application  ──►  domain
             │
             ▼
           ports  ◄──  adapters (DeyeCloud, Open-Meteo, SQLite, clock)
```

| Layer | Package | What it holds | May import |
|---|---|---|---|
| Domain | `domain/` | Value objects and rules, no I/O: `TimeOfUseTable`/`TimeOfUseSlot`, `Reading`, `Forecast`, `LoadProfile`, `EnergyBalance`, the planner rules (`FloorRule`, `ReserveRule`, `ManualChargeRule`, Strategy pattern behind `PlannerRule`), `JustInTimeCharge`, `OutageSimulation`, `PlannerSettings` and its `SettingsCodec` | the standard library and other domain modules |
| Ports | `ports.py` | Abstract interfaces the application depends on: `InverterGateway`, `ForecastProvider`, `EnergyHistorySource`, the repositories, `KeyValueStore`, `Clock` | domain |
| Application | `application/` | Use cases: collection (`CollectReadings`, `RefreshForecast`, `RefreshInverterSettings`), history (`RecordToday`, `SyncDailyEnergy`, `BackfillFrames`), `PlannerService`, `TimeOfUseService` (Command: send → wait for the order → read back → journal), `ManualChargeService`, `ChargeSettingsService`, `ProfileService`, views and statistics, `JobScheduler` | domain, ports |
| Adapters | `adapters/` | `DeyeCloudGateway` and `DeyeCloudHistory` (token, signed requests, order polling, mapping), `OpenMeteoForecast`, the SQLite repositories, `SystemClock` | domain, ports |
| Web | `web/` | FastAPI app, one controller class per area (`PlanApi`, `TimeOfUseApi`, `ManualChargeApi`, …), the login gate, page controller, templates, CSS, JavaScript modules | application, domain |
| Composition root | `container.py`, `config.py`, `__main__.py` | Reads the configuration, builds every object and wires them (`build_services`), starts the scheduler and the web server | everything |

Collaborators are passed in through constructors. Services with many of them take
a parameter object (`PlannerDependencies`, `ManualChargeDependencies`,
`TimeOfUseDependencies`).

## Data flow

1. **Collection** (scheduler, every 5 min): `CollectReadings` reads live values
   through `InverterGateway` and stores them (`SqliteReadingRepository`).
   Inverter settings every 30 min; forecast every hour; daily energy and history
   backfill from DeyeCloud's station history. Intervals: config `[intervals]`.
2. **Planner check** (every 15 min, and "Run a check now"): `PlannerService`
   refreshes the forecast, builds a `PlannerContext` (SOC, base table, forecast
   corrected by today's actual ÷ forecast, house load profile from history, grid
   charge power from the inverter's settings), evaluates the rules in order
   (floor → outage reserve → manual charge; later rules win on a slot), merges
   them into one table, compares it with the inverter's table and, in Live mode
   and within the write limits, sends it through `TimeOfUseService`.
3. **Every decision and every command** goes to the journal
   (`SqliteJournalRepository`); the Plan and Log pages read it.
4. **Web**: pages are server-rendered shells; JavaScript modules fetch JSON from
   `/api/...` and draw tiles, tables and Chart.js charts.

## Storage

One SQLite database (path in the machine config, `[storage] database`): readings,
forecast hours, daily energy, journal, and a key-value store for settings,
inverter state (last read table and settings), profiles, the to-do list, the manual charge and the
password hash. It survives redeploys; nothing in it is needed from the cloud to
show history.

## Configuration

Three levels, later wins: the packaged `defaults.toml`, the machine's file
(`DEYE_INVERTER_CONFIG`, in the private `opts/` repository), environment variables
`DEYE_INVERTER_<SECTION>_<KEY>`. Credentials are a separate file in `opts/`.
Planner values are not in the config: they are settings edited in the UI
(Settings page) and stored in the database, with the shipped defaults in
`src/deye_inverter/domain/settings.py`.

## Quality gates

`pytest` with branch coverage (minimum 80 %), `ruff`, `ruff format`, `mypy --strict`,
and the reviewer's gate (`gate.sh --repo deye-inverter`) before every commit.
Tests use fakes behind the ports (`tests/fakes.py`), never the network.

## Deployment

See [`deploy.md`](deploy.md): the committed tree and `opts/` are copied to the
host, `deploy/install.sh` installs the package in a virtual environment and
restarts the systemd service. Only the restart is allowed without a password on
the host.
