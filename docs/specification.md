# deye-inverter — specification (draft for agreement)

Status: **agreed 2026-10-05**, extended since (sections 11–13). Behaviour
changes start here. Decisions taken in the design discussion are marked
*(decided)*; everything else is a proposal.

## 1. Purpose

A web application, running in a home-lab container, that:

1. collects the inverter's live values and settings from DeyeCloud and keeps
   their history locally, so the history stays readable without the cloud;
2. shows live values, history, the solar forecast and forecast-vs-actual;
3. shows and edits the inverter's Time of Use table;
4. runs a planner that changes the Time of Use table from the weather
   forecast, so the battery holds enough charge when it is needed and the
   grid is used only when the sun will not do the job.

Out of scope for now: a phone app (the web UI works in a phone browser),
local RS485/Modbus access, notifications, Solcast.

## 2. Facts the design relies on (verified 2026-10-05)

| Fact | Source |
|---|---|
| A Personal DeyeCloud account can write Time of Use through `/order/sys/tou/update`; the order reached status 666 (executed) and the table read back unchanged | test from CT 111 |
| App permissions: Station Monitoring, Device Monitoring, Comission Control | developer portal |
| One station with one logger and one 8 kW inverter (identifiers: private settings, `opts/`), Modbus protocol `0201`; battery 315 Ah (~16 kWh usable) | API |
| Time of Use has exactly 6 slots; each: start time, SOC %, power W, voltage, grid charge on/off, generator on/off. A write sends all 6 | API |
| The logger talks only to the cloud (MQTT over TLS, port 8883, AWS Frankfurt); no local data path without RS485 | router connection table |
| Router and Proxmox are on the inverter's backup output: during a grid outage the cloud path works as long as the ISP does | owner |
| Panels: 6 kWp, facing south, tilt 27–30°, no shading (the DeyeCloud plant page says 8 kWp: that is the inverter's rating, not the panels') | owner |

## 3. Decisions *(decided)*

- Data source: DeyeCloud only for now. The data source is an interface; a
  local RS485/Modbus implementation can replace or join it later without
  changing the planner or the UI.
- The only inverter setting the application writes is the Time of Use table.
  Battery charge settings (grid charge current etc.) are the inverter's
  existing ones; the application reads them, never changes them.
- Every write is verified by reading the table back, and is logged.
- Automation modes: **Off**, **Dry-run** (decides and shows, sends nothing),
  **Live**. It starts in Dry-run and stays there until the owner switches it in
  the UI after agreeing what it must do.
- The UI is in English and generic: no mention of what the reserve is for.
- Login: one password, set by the owner at the first visit.
- Every rule parameter is configurable in the UI; the application ships
  defaults (section 6).
- Location: private configuration (`opts/<os>/config.toml`, `[site] latitude`,
  `longitude`); editable in the UI afterwards.

## 4. Planner rules

`docs/planner.md` explains the planner step by step (rules rewritten and unified
on 2026-10-07). Summary:

- **Floor**: every slot lets the battery run down to 30 % (the inverter's own
  low-battery limit), no grid charge.
- **Outage reserve**: the slots of the protected moments (16:00 and every slot
  start after it before 09:00: 16:00, 17:00, 21:00, 01:00, 05:00) hold what a
  grid outage at that moment would need until the panels take over (hourly
  simulation: essential load, half of the forecast sun, battery not below 20 %,
  at most 90 %). Reached from the grid only if the projection falls short, and
  as late as possible (the slot start is moved). A running slot holds its
  moment's reserve. Every day.
- **Manual charge**: overrides both (section 13).
- Later rules win: floor, reserve, manual. Every check (every 15 min, all day)
  fetches the forecast again. Every value is a setting (Settings page, including
  "Tuning"); job intervals are in the configuration file.

### 4.3 Safety limits

- No SOC below 20 % (the BMS shutdown limit) or above 100 %.
- At most N writes per day (default 6). A failed write is not retried
  blindly; it is logged and shown.
- If the forecast or the cloud is unavailable, the planner writes nothing and
  the last table stays in force.

## 5. User interface

| Screen | What it shows / does |
|---|---|
| First run | Set the password |
| Now | Live values: solar power, house load, backup-output load, battery SOC / power / voltage, grid power, inverter state, age of the data |
| History | Charts per day / week / month from the local database; daily energy totals |
| Forecast | Solar forecast for today and the next days; forecast vs actual production; the correction ratio |
| Plan | What the planner decided at each check and why (projected SOC, energy figures), what it will do next; mode Off / Dry-run / Live |
| Time of Use | The current table read from the inverter; edit and send manually; result of the order |
| Settings | reserve rule parameters, days and exception dates, location and panel data, polling intervals, password |
| Log | Every command sent, its order status and read-back result; errors |

Files: one HTML template per screen, CSS and JavaScript in separate files, no
inline scripts or styles.

## 6. Defaults

| Parameter | Default |
|---|---|
| Floor | 30 %, no grid charge |
| Outage reserve: protected from / until | 16:00 / 09:00, every day |
| Outage load: 16–20 / 20–22 / 06–09 / other hours | 0.9 / 0.4 / 1.0 kW / history + 25 %, at most 0.5 kW |
| Outage reserve: forecast trusted / highest reserve | 50 % / 90 % |
| Checks / start tolerance / reserve tolerance | every 15 min / 15 min / 3 points |
| Consumption estimate window | last 7 days |
| Live-value polling | every 5 min (DeyeCloud refreshes every 3–5 min) |
| Settings polling | every 30 min, and right after every write |
| Writes per day | at most 6 |
| Battery capacity | 16 kWh |
| Panels | 6 kWp, azimuth 0° (south), tilt 28°, performance ratio 0.82 (measured) |

## 7. Architecture

Layers, dependencies pointing inwards:

- **Domain** — entities and rules, no I/O: `TimeOfUseTable`, `TimeOfUseSlot`,
  `Reading`, `Forecast`, `PlannerRule` (Strategy: `ReserveByTimeRule`,
  `OvernightFloorRule`), `Decision`.
- **Application** — use cases: `CollectReadings`, `RefreshForecast`,
  `RunPlanner`, `ApplyTimeOfUse` (Command: send → wait for order → read back
  → log), `EditTimeOfUse`.
- **Ports** (interfaces): `InverterGateway` (read live values, read/write
  Time of Use, read battery settings), `ForecastProvider`, repositories,
  `Clock`.
- **Adapters**: `DeyeCloudGateway` (token refresh, order polling),
  `OpenMeteoForecast`, SQLite repositories, web controllers.
- **Composition root** wires everything from configuration; a scheduler runs
  the jobs.

Stack: Python 3.13, FastAPI + Uvicorn, httpx, Pydantic, SQLite, APScheduler;
front end in plain HTML/CSS/JavaScript modules with Chart.js served locally
(no CDN). Tests: pytest (coverage ≥ 80 %), ruff, mypy.

## 8. Configuration and deployment

- `opts/` (private repository `deye-inverter-opts`): `linux/config.toml`,
  `macos/config.toml`, credentials. One configuration module reads them;
  environment variables prefixed `DEYE_INVERTER_` override.
- Public repository: `config.example.toml` with placeholders only;
  `_meta/tools/check-paths.sh` before every push.
- Runtime data (SQLite database) under the runtime root:
  `<runtime-root>/deye-inverter/`.
- Production: CT 111, Python virtual environment, systemd service on port
  8080 (reachable from the LAN and Tailscale only).
- Development on the Mac in the project's own conda environment.

## 9. Delivery order (MVP first)

1. Collector + local database + screens Now, History, Time of Use (read only).
2. Forecast + planner in Dry-run + screens Forecast, Plan, Settings, Log.
3. Manual Time of Use editing and sending; mode Live.
4. Later: calibration helpers, RS485/Modbus source, Solcast, notifications.

## 10. Open points

- None at the moment (2026-10-06).

## 11. Statistics (added 2026-10-05)

The History screen became **Statistics**: periods Day, Week, Month, Year and
Lifetime, each with previous/next navigation and a date picker.

- Totals per period: consumed, **from solar** (consumption minus energy bought:
  panels directly or through the battery), **from grid** (energy bought), solar
  produced, battery charged and discharged, self-sufficiency (share of
  consumption not taken from the grid).
- Charts: Day and Week show the power curves (solar, consumption, grid,
  battery) and SOC; Month shows daily bars (from solar / from grid), solar
  produced and the day's SOC minimum and maximum; Year shows monthly bars,
  Lifetime yearly bars plus the inverter's own lifetime counters.
- Data: finished days come from DeyeCloud's station history (daily energies,
  synced hourly: everything once, then the last 31 days); today comes from the
  live readings. Power curves of days the collector did not see are filled from
  DeyeCloud's 5-minute frames, a few days per run, back to the day the station
  started (2026-06-13).

## 12. Charging settings and profiles (added 2026-10-05)

- **Charging settings** (read every 30 minutes with the Time of Use
  table): grid charge master switch, grid charge current, Time of Use on/off,
  work mode, battery max charge/discharge current. Read through DeyeCloud's
  `/strategy/dynamicControl/read` order (registers 230, 232, 244, 248, 210,
  211). Shown on Now and on Time of Use. The planner's grid charging power now
  uses min(grid charge current, max charge current) × battery voltage
  (60 A ≈ 3.1 kW, before: 100 A ≈ 5.1 kW).
- How they combine: the grid charge switch is the master; a Time of Use slot
  with *Grid charge* ticked charges from the grid only while it is on, and only
  up to that slot's SOC.
- **Grid charge switch** (Time of Use page): turns the master switch on or off
  through DeyeCloud `/order/battery/modeControl` (`GRID_CHARGE`), then reads the
  settings back and journals the change (kind *setting*). The inverter's
  "grid charge start %" is not exposed by the DeyeCloud reads used so far, so it
  is not shown yet.
- **Profiles**: named Time of Use tables kept in the application (*Save profile as…*, load a profile into the editor, delete). *Send to
  inverter* applies a profile at once, with the same read-back check as any
  other write, and only while the automation mode is **Off** (Plan page), so
  the planner cannot overwrite it.
- Profiles created on 2026-10-05: *default* (every slot 30 %), *backup* (50 %),
  a fourth holding the inverter's table on that day, *safety* (75 %); times, power and
  grid charge flags as in the inverter's table.

## 13. Manual charge (added 2026-10-06)

On the Plan page: battery SOC, battery power (charging / discharging), grid
charge switch, and a "charge to X %" command — now or ready by a time, with
an optional hold-until time (hold = ready time: release at the ready time).
Live mode only; it overrides every planner rule while active; the grid charge
switch is turned on for it if needed and restored at the end. Details:
`docs/planner.md` section 6.
