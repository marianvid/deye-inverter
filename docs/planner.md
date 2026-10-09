# How the planner works

The planner decides what the inverter's **Time of Use table** should contain and,
in Live mode, sends it. Every value named here is on the Settings page (defaults
in brackets); nothing that drives a decision is fixed in the code.

## 1. Words

- **SOC**: how full the battery is, in percent (16 kWh battery: 1 % ≈ 0.16 kWh).
- **Time of Use table**: six rows on the inverter. Each row (**slot**) starts at a
  clock time and lasts until the next one starts. The rows start at 01:00, 05:00,
  09:00, 13:00, 17:00 and 21:00 (the times of the base table).
- **Slot SOC**: while the grid is present, the battery does not supply the house
  below this level; the house then takes power from the grid. In an outage the
  inverter uses the battery anyway, down to 20 %.
- **Grid charge (per slot)**: when ticked and the battery is below the slot SOC,
  the inverter charges from the grid at once (≈ 3.1 kW) up to the slot SOC.
- **Outage**: the grid fails; the house runs only on the battery and the panels.
- **Reserve**: the SOC an outage at that moment would need (section 3).
- **Check**: one run of the planner, every 15 minutes [tuning], each time with a
  fresh weather forecast.

## 2. Three rules, applied in this order (a later rule wins on the same slot)

1. **Floor** — every slot: the battery may run down to **30 %** [floor], no grid
   charge.
2. **Outage reserve** — the **protected moments** are 16:00 [protected from] and
   every slot start after it before 09:00 [protected until]: **16:00, 17:00,
   21:00, 01:00, 05:00**. Their slots get the reserve as their SOC.
3. **Manual charge** — when you order one on the Plan page (section 6).

So the 09:00 slot always has the floor; the 13:00, 17:00, 21:00, 01:00 and 05:00
slots have the reserve.

## 3. The reserve: "if the grid failed now, would we get to the morning?"

For a protected moment the planner simulates an outage hour by hour:

- **The house uses its outage load** (essential consumers only):
  16:00–20:00 **0.9 kW** (lights and essential appliances, a 1 kW heater half
  of the time),
  20:00–22:00 **0.4 kW**, 06:00–09:00 **1.0 kW**, any other hour the house's
  real load for that hour from the last 7 days **+25 %**, at most **0.5 kW**.
- **The panels give half of the forecast** [share trusted 0.5].
- **The battery may not go below 20 %** (it shuts down there).
- **The outage ends** when, after the night, half of the forecast sun covers the
  outage load again (in October about 09:00–10:00; on a cloudy morning later).

The reserve is the lowest SOC that gets through, at most **90 %**. With a
generator ["generator available"], the battery only has to bridge its start
[1 h].

## 4. Reaching the reserve: from the grid only if needed, as late as possible

At each check, for each protected moment:

- **The moment is still ahead** (for example 10:00, for 16:00): the planner
  projects the SOC at the moment with normal use (house load from history, the
  forecast sun corrected by today's actual ÷ forecast so far).
  - Projection ≥ reserve: the slot gets the reserve, **no grid charge**.
  - Projection < reserve: it computes how long the grid needs (deficit ÷ 3.1 kW
    × 1.2 margin) and **moves the slot's start** to that latest time (5-minute
    steps), with grid charge on. Until then the previous slot applies, so nothing
    is bought earlier. The inverter starts by itself at that time, even if the
    server is down. Later checks move the start later or cancel it when the sun
    does better.
- **The moment's slot is running** (for example 23:00, inside 21:00–01:00): the
  slot keeps the reserve computed for its moment; grid charge only if the battery
  is already below it.

Fewer writes: a planned start moves only by more than 15 minutes, and a reserve
is rewritten only when it changes by more than 3 points. Most checks therefore
end in "no change". After a write the table is read back up to 4 times, 15 s
apart, because DeyeCloud shows a new table only after a while.

Write limits, a safety net against a planner fault (neither the inverter nor
DeyeCloud imposes one):

- A table that **keeps more in the battery** (a higher slot SOC, grid charge
  switched on, or grid charging starting earlier) is sent at once.
- A table that **lowers the protection** or moves a grid start later waits until
  30 minutes [minutes between writes] after the previous write.
- At most **24 tables** a day [writes per day]; tables that keep more in the
  battery may go on up to **48** [writes per day when raising the protection],
  so a fault cannot block a needed charge. Both limits count the same writes;
  the Plan page shows how many of each are left.

## 5. A day, from 09:00

| Time | Slot | What the inverter does |
|---|---|---|
| 09:00–13:00 | floor 30 % | the battery supplies the house down to 30 %; the sun recharges it |
| 13:00–16:00 | reserve for 16:00 | sunny: no grid; cloudy: grid charge from the moved start, as late as possible |
| 16:00–17:00 | same slot, now holding | battery kept at least at the 16:00 reserve |
| 17:00–21:00 | reserve for 17:00 | the battery supplies the house down to that level, then the grid |
| 21:00–01:00 | reserve for 21:00 | same; higher when the next morning is cloudy |
| 01:00–05:00 | reserve for 01:00 | lower: less night is left |
| 05:00–09:00 | reserve for 05:00 | covers the morning until the panels take over |

## 6. Manual charge (Plan page)

**Charge to X %**, **Now** or **Ready by** a time (just-in-time, as in section 4),
optional **Hold until**: until then the battery stays at least at X % (empty =
release when reached, or at the ready time). It overrides every rule, works only
in Live mode, switches the grid charge master switch on if needed and back off at
the end, and lasts at most 48 hours [tuning]. While it is on, the mode buttons are
locked.

## 7. What the planner never does

- Writes outside Live mode.
- Goes below the "lowest SOC ever written" [20 %].
- Changes anything but the Time of Use table (except the grid charge switch for a
  manual charge you ordered).
- Sends profiles: they are sent by hand, only while the mode is Off.

## 8. Known limits

- The inverter's "grid charge start %" (87 %) cannot be read through DeyeCloud,
  so its effect is not modelled.
- With zero export and a full battery the inverter curtails the panels, so the
  actual ÷ forecast correction can look worse than the weather was. It only
  happens when the battery is already full, so it does not cause grid charging.
- Intervals of the background jobs (readings every 5 min, inverter settings 30,
  forecast 60) are in the configuration file, section `[intervals]`.
