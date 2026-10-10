import { api } from "./api.js";
import { el, fillTable, guarded, notify } from "./dom.js";
import { localTime } from "./format.js";
import { refreshModeBadge } from "./layout.js";
import { bindManualForm, renderManual } from "./manual-charge.js";
import { renderReadOnly } from "./tou-table.js";

const HELP = {
  off: "The planner does not run.",
  "dry-run": "The planner decides and records what it would send, but sends nothing.",
  live: "The planner sends the table to the inverter when its rules require a change.",
};
const RULE_TITLES = {
  floor: "Battery floor", reserve: "Outage reserve", manual: "Manual charge",
};
const FIGURES = {
  hours_left: ["Hours to target", ""], solar_kwh: ["Solar expected", "kWh"],
  load_kwh: ["Load expected", "kWh"], projected_soc: ["Projected SOC", "%"],
  target_soc: ["Target SOC", "%"], deficit_kwh: ["Missing", "kWh"],
  grid_hours: ["Grid charging", "h"], grid_from: ["Grid charge from", ""],
  floor_soc: ["Floor", "%"],
};

function figure(key, value) {
  const [label, unit] = FIGURES[key] ?? [key.replaceAll("_", " "), ""];
  return el("span", {}, `${label}: ${value}${unit ? ` ${unit}` : ""}`);
}

function ruleCard(rule) {
  return el("div", { class: "rule-card" },
    el("strong", {}, RULE_TITLES[rule.rule] ?? rule.rule),
    el("p", {}, rule.summary),
    el("div", { class: "figures" }, Object.entries(rule.figures).map(([k, v]) => figure(k, v))));
}

function renderPreview(decision) {
  const box = document.getElementById("preview");
  const table = el("table", { class: "data" });
  box.replaceChildren(
    el("p", {}, el("span", { class: `status ${decision.status}` }, decision.status), ` — ${decision.message}`),
    ...decision.rules.map(ruleCard),
    decision.desired ? el("h2", {}, "Table the rules produce (changed cells highlighted)") : null,
    decision.desired ? table : null);
  if (decision.desired) renderReadOnly(table, decision.desired, decision.changed_slots);
}

function renderMode(mode) {
  for (const button of document.querySelectorAll("#mode-switch button")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
  document.getElementById("mode-help").textContent = HELP[mode];
  refreshModeBadge(mode);
}

// One counter, two limits: a table that keeps more in the battery has a higher one.
function renderWrites(data) {
  const left = (limit) => Math.max(0, limit - data.writes_today);
  document.getElementById("writes-today").textContent = String(data.writes_today);
  document.getElementById("writes-lowering").textContent =
    `Lowering the protection: ${left(data.max_writes_per_day)} of ${data.max_writes_per_day} left.`;
  document.getElementById("writes-raising").textContent =
    `Raising it: ${left(data.max_raising_writes_per_day)} of ${data.max_raising_writes_per_day} left.`;
}

function render(data) {
  renderMode(data.mode);
  renderWrites(data);
  renderPreview(data.preview);
  document.getElementById("next-check").textContent = data.next_check ? localTime(data.next_check) : "–";
  renderInverterTable(data.inverter_table);
  renderDecisions(data.decisions);
}

// The table on the inverter now: the settings every decision below is measured against.
function renderInverterTable(current) {
  const note = document.getElementById("inverter-table-read");
  const table = document.getElementById("inverter-table");
  if (!current) {
    note.textContent = "Inverter table: not read yet.";
    table.replaceChildren();
    return;
  }
  note.textContent = `On the inverter now (read ${localTime(current.read_at)}):`;
  renderReadOnly(table, current.slots, []);
}

// What changed comes first; the rules' reasoning is folded below it.
function changesCell(d) {
  if (d.changes && d.changes.length) return el("div", { class: "changes" }, d.changes.map((c) => el("div", {}, c)));
  return el("span", { class: "muted" }, d.changed_slots && d.changed_slots.length ? "table differs" : "–");
}

function reasonCell(d) {
  return el("details", {}, el("summary", {}, "why"), el("p", {}, d.rules.map((r) => r.summary).join(" ")),
    d.message ? el("p", { class: "muted" }, d.message) : null);
}

function renderDecisions(decisions) {
  fillTable(document.getElementById("decisions"), ["When", "Result", "What changes", "Reason"],
    decisions.map((d) => [`${localTime(d.at)} (${d.trigger}, ${d.mode})`,
      el("span", { class: `status ${d.status}` }, d.status), changesCell(d), reasonCell(d)]));
}

async function load() {
  const [plan, manual] = await Promise.all([api.get("/api/plan"), api.get("/api/manual-charge")]);
  render(plan);
  renderManual(manual);
  lockModeSwitch(Boolean(manual.charge));
}

bindManualForm(load);

// While a manual charge is on, the automation stays in Live (leaving Live would cancel it).
function lockModeSwitch(locked) {
  for (const button of document.querySelectorAll("#mode-switch button")) button.disabled = locked;
  if (locked) {
    document.getElementById("mode-help").textContent = "Locked in Live while a manual charge is on. Switch the manual charge off first.";
  }
}

for (const button of document.querySelectorAll("#mode-switch button")) {
  button.addEventListener("click", () => guarded(button, async () => {
    const mode = button.dataset.mode;
    if (mode === "live" && !window.confirm("Live mode lets the planner write to the inverter. Continue?")) return;
    await api.post("/api/plan/mode", { mode });
    await load();
    notify(`Mode set to ${mode}.`);
  }));
}
document.getElementById("run-now").addEventListener("click", (e) => guarded(e.target, async () => {
  const decision = await api.post("/api/plan/run");
  await load();
  notify(`Check done: ${decision.status} — ${decision.message}`);
}));

load().catch((error) => notify(error.message, "error"));
