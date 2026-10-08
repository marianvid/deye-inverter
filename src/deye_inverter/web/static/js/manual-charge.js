// Battery state and the manual "charge to X %" switch on the Plan page.
import { api } from "./api.js";
import { notify, tile } from "./dom.js";
import { kw, localTime } from "./format.js";

const form = document.getElementById("manual-form");
const toggle = document.getElementById("manual-toggle");
const note = document.getElementById("manual-note");
const fields = () => form.querySelectorAll("input:not(#manual-toggle)");

const HELP = "Switch on to charge: Now, or Ready by a time (grid charging starts as late as possible). "
  + "Hold until keeps at least that level until the time; empty = release when reached. "
  + "Overrides the plan while on.";

function batteryTiles(status) {
  const power = status.battery.power;
  // DeyeCloud reports battery power positive while discharging, negative while charging.
  const direction = power === null ? "" : power < -20 ? "charging" : power > 20 ? "discharging" : "idle";
  const grid = status.grid_charge_enabled === null ? "unknown" : status.grid_charge_enabled ? "on" : "off";
  return [
    tile("Battery", status.battery.soc ?? "–", "%", status.battery.at ? localTime(status.battery.at) : "", "--battery"),
    tile("Battery power", power === null ? "–" : kw(Math.abs(power)), "kW", direction, "--battery"),
    tile("Grid charge switch", grid, "", "", "--grid"),
  ];
}

function clock(iso) {
  return iso ? new Date(iso).toTimeString().slice(0, 5) : "";
}

function describe(charge) {
  const start = charge.ready_at ? `ready by ${localTime(charge.ready_at)}` : "now";
  const hold = charge.hold_until ? `, held until ${localTime(charge.hold_until)}` : "";
  return `On: charging to ${charge.target_soc}% ${start}${hold}. Switch off to cancel.`;
}

function syncReadyField() {
  const ready = form.elements.start.value === "ready";
  form.elements.ready_time.disabled = toggle.checked || !ready;
}

function showCharge(charge) {
  form.elements.target_soc.value = charge.target_soc;
  form.elements.start.value = charge.ready_at ? "ready" : "now";
  form.elements.ready_time.value = clock(charge.ready_at);
  form.elements.hold_until.value = clock(charge.hold_until);
}

export function renderManual(status) {
  document.getElementById("battery-now").replaceChildren(...batteryTiles(status));
  const live = status.mode === "live";
  toggle.checked = Boolean(status.charge);
  toggle.disabled = !live && !status.charge;
  if (status.charge) showCharge(status.charge);
  for (const input of fields()) input.disabled = toggle.checked || !live;
  syncReadyField();
  form.classList.toggle("active", toggle.checked);
  note.textContent = status.charge ? describe(status.charge) : live ? HELP : "Manual charge is available in Live mode (Plan page, Automation mode).";
}

async function start() {
  const data = new FormData(form);
  const ready = form.elements.start.value === "ready";
  if (ready && !form.elements.ready_time.value) throw new Error("Choose the Ready by time.");
  await api.post("/api/manual-charge", {
    target_soc: Number(data.get("target_soc")),
    ready_time: ready ? form.elements.ready_time.value : null,
    hold_until: form.elements.hold_until.value || null,
  });
  notify("Manual charge started.");
}

async function cancel() {
  await api.delete("/api/manual-charge");
  notify("Manual charge cancelled; the plan applies again.");
}

export function bindManualForm(onChange) {
  for (const radio of form.elements.start) radio.addEventListener("change", syncReadyField);
  form.addEventListener("submit", (event) => event.preventDefault());
  toggle.addEventListener("change", async () => {
    const turningOn = toggle.checked;
    toggle.disabled = true;
    try {
      await (turningOn ? start() : cancel());
    } catch (error) {
      notify(error.message, "error");
    } finally {
      toggle.disabled = false;
      await onChange();
    }
  });
}
