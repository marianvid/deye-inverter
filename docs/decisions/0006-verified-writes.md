# 0006 — Every write is read back and journaled

Date: 2026-10-05 · Status: accepted (retries added 2026-10-07)

**Context.** DeyeCloud accepts an order and executes it later; the table it shows changes
only after a while.

**Decision.** After a write, read the table back up to N times, M seconds apart
(settings); the result is "executed" (matches) or "mismatch". Both count as writes.
Every command and every decision is journaled with the reason.

**Consequences.** A write that did not take effect is visible on the Plan and Log pages;
a slow cloud costs a re-send at the next check.
