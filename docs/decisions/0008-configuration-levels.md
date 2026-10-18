# 0008 — Configuration in three levels; secrets and machine values in a private repository

Date: 2026-10-08 · Status: accepted (packaged defaults 2026-10-18)

**Context.** The repository is public; the home's location, device serials, hosts and
DeyeCloud credentials are private.

**Decision.** Packaged `defaults.toml` < the machine's file in the private `opts/`
repository < `DEYE_INVERTER_<SECTION>_<KEY>` environment variables. Credentials are a
separate file in `opts/`. Planner values are UI settings stored in the database. No URL,
path, address or identifier in the code.

**Consequences.** The public code runs anywhere with its own `opts/`; `check-paths.sh`
guards each push.
