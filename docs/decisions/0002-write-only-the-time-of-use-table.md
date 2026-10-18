# 0002 — The application writes only the Time of Use table

Date: 2026-10-05 · Status: accepted

**Context.** The inverter has many settings; a wrong write can damage the battery or
cut the house off.

**Decision.** The planner changes only the Time of Use table (six slots: start, SOC,
grid charge). The only other write is the grid charge master switch, for a manual
charge started by the owner or from its switch on the Plan page. Charge currents,
work mode and battery limits are read, never written.

**Consequences.** The blast radius of a bug is limited to how far the battery may
discharge and when it charges from the grid.
