# 0003 — Planner rules as strategies, merged in a fixed order

Date: 2026-10-06 · Status: accepted

**Context.** Several concerns set the same slots: a minimum level, a reserve for outages,
a charge ordered by hand.

**Decision.** Each concern is a `PlannerRule` (Strategy pattern) returning slot
overrides plus figures and a summary. They are applied in order — floor, outage
reserve, manual charge — and a later rule wins on the slots it touches.

**Consequences.** A new concern is a new rule; each rule is tested alone; every decision
records each rule's reasoning for the Plan page.
