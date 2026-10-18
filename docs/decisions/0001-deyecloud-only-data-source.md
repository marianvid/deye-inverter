# 0001 — DeyeCloud OpenAPI as the only data source

Date: 2026-10-05 · Status: accepted

**Context.** The inverter's Wi-Fi logger talks only to the cloud: no Modbus TCP, no local
API. A local RS485/Modbus link would need extra hardware and wiring.

**Decision.** Read and write through the DeyeCloud OpenAPI only, behind the
`InverterGateway` port.

**Consequences.** No extra hardware; data lags 3–5 minutes; writes are orders that the
cloud executes later (see 0006); the app needs the internet. A local source can be
added later as another adapter without touching the domain or the planner.
