# Forecast calibration

## 2026-10-05 — Open-Meteo against the station's own history

Data: 114 days (2026-06-13 to 2026-10-04) of 5-minute power frames from
DeyeCloud; Open-Meteo **historical forecast** API (what the forecast said at the
time), hourly `global_tilted_irradiance` for the station's location (private settings), tilt 28°,
azimuth 0° (south), 6 kWp. Script: scratch, not part of the application.

Curtailment: with zero export, the inverter limits the panels when the battery
is full, so hours with battery SOC ≥ 95 % are excluded from every comparison.

| Result | Value |
|---|---|
| Uncurtailed daylight hours | 466 |
| Measured performance ratio (actual ÷ irradiance × 6 kWp) | **0.82** (the default was 0.80) |
| Hourly correlation forecast vs actual | 0.86 |
| Hourly error after calibration | mean 0.00 kWh, typical (standard deviation) 0.66 kWh |
| Days mostly uncurtailed (≥ 80 % of daylight hours) | **4 of 113** |
| Daily error on those 4 days | median 42 % |
| House load 08:00–17:00 | median 9.0 kWh/day (summer, with air conditioning) |

Conclusions:

- The hourly model is sound: the performance ratio of 0.82 comes from 466
  hours and matches the physical expectation.
- Day-level accuracy cannot be judged from this summer: the battery was full on
  almost every day, so only 4 days show what the panels could really produce.
  Day-level validation needs autumn/winter days, when the battery is not full by
  noon.
- Overnight-rule threshold: lowering the night floor from 55 % to 25 % means the
  next day must bring back ~8 kWh to the battery plus cover the daytime load
  (~9 kWh in summer) to reach the 75 % target, i.e. ~17 kWh. The default of
  15 kWh is too low; 17 kWh is the better starting value, to be revisited with
  winter data (daytime load will differ).
- Solcast cannot be compared on this history: the free Hobbyist plan returns
  only the last 7 days of estimated actuals. Comparison starts when the account
  exists and grows day by day.
