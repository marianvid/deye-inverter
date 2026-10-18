# 0004 — Outage reserve from an hourly simulation, not fixed thresholds

Date: 2026-10-07 · Status: accepted (replaces "75 % at 16:00" and a fixed morning reserve)

**Context.** The reserve exists so that a grid outage in the evening or at night does
not leave the house without power until the sun is back. Fixed levels were too high
on sunny days (energy bought for nothing) and blind to a dark next morning.

**Decision.** For each protected moment (16:00 and every slot start until 09:00) simulate
an outage hour by hour: essential load only, half of the forecast sun, battery not
below its shutdown level, outage over when the sun covers the load again. The reserve
is the lowest SOC that gets through, capped (90 %). Every load and margin is a setting.

**Consequences.** Lower reserves on sunny days, higher before dark days; the reserve
follows the forecast, so it changes during the day (see 0007 on write limits).
