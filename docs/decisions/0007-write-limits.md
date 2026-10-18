# 0007 — Write limits that never block a needed charge

Date: 2026-10-08 · Status: accepted (revised 2026-10-09)

**Context.** A planner fault once wrote 16 tables in a night; a flat daily limit of 6 then
blocked the planner for a whole day, including raising the reserve. Neither the inverter
nor DeyeCloud imposes a limit; the limit is ours.

**Decision.** Two limits on one daily counter: a table that lowers the protection (lower
SOC, grid charge off, grid start later) is sent at most 24 times a day and 30 minutes
after the previous write; a table that keeps more in the battery is sent at once, up to
48 a day. All three are settings; the Plan page shows how many of each are left.

**Consequences.** A fault cannot write without bound, and a needed charge is never held
back by the limit.
