# AGENTS.md — deye-inverter

The rules in `work/_meta/CONVENTIONS.md` apply. This file adds to them.

## Purpose

A web application (served from a home-lab container) that:
- collects inverter, battery and grid data from DeyeCloud and stores it locally;
- shows real-time values, history, weather forecast and forecast-vs-actual;
- edits the inverter's Time of Use table on request;
- runs a planner that keeps the battery at a target state of charge before a
  given time on weekdays, charging from the grid only when the forecast says
  the sun will not do it.

## Rules

1. The specification in `docs/` was agreed with the owner on 2026-10-05; change it
   before changing behaviour it describes.
2. The automation starts in dry-run mode (decides and displays, sends nothing)
   and stays there until the owner switches it from the interface.
3. The application writes only the Time of Use table, and the grid charge
   master switch for a manual charge the owner starts. Every write is verified by reading the table back, and logged.
4. Data sources sit behind one interface; DeyeCloud is the first
   implementation. A local source (RS485/Modbus) may be added later without
   touching the interface or the planner.
5. Credentials and machine values live in `opts/` (private repository
   `deye-inverter-opts`), read by one configuration module. The public
   repository ships `config.example.*` with placeholders only.
6. Code: clean code, SOLID, object-oriented design, design patterns where they
   earn their place. HTML, CSS and JavaScript in separate files.
7. User interface language: English.
