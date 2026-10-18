# 0005 — Grid charging as late as possible, by moving a slot's start

Date: 2026-10-06 · Status: accepted

**Context.** A Time of Use slot with grid charge on charges at once, up to the slot's
SOC. Charging early buys energy the sun might still deliver.

**Decision.** When the projection falls short of a reserve, compute how long the grid
needs (deficit ÷ charge power × margin) and move the start of the slot that holds the
deadline to that latest time. The inverter starts on its own, even if the server is
down; later checks move the start later or cancel it as the forecast improves.
A start is kept while it is within a tolerance (15 min) or once charging has begun.

**Consequences.** Least energy bought; slot starts change during the day and must be
damped to limit writes (0007).
