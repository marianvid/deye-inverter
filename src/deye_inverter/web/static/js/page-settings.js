import { api } from "./api.js";
import { el, guarded, notify } from "./dom.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Each field: [key, label, type, help]. Types: bool, int, float, time, times, dates, weekdays.
const SECTIONS = [
  { key: null, title: "General", fields: [
    ["max_writes_per_day", "Writes per day (max)", "int", "A safety net against a planner fault. A table that keeps more in the battery (higher SOC, grid charge on or earlier) is sent anyway, up to twice this number."],
    ["min_minutes_between_writes", "Minutes between writes (min)", "int", "A table that lowers the protection or moves a grid start later waits this long after the previous write."],
  ] },
  { key: "reserve", title: "Outage reserve", fields: [
    ["enabled", "Enabled", "bool", "Off: the floor applies everywhere."],
    ["protect_from", "Protected from", "time", "From this time the battery keeps what a grid outage would need until the panels take over."],
    ["protect_until", "Protected until", "time", "The slot starts between these two times are protected too."],
    ["weekdays", "Days", "weekdays", ""],
    ["skip_dates", "Skip dates", "dates", "Comma-separated dates (YYYY-MM-DD)."],
    ["evening_kw", "Outage load in the evening (kW)", "float", "From 'protected from' to 'evening until': lights and the essential appliances, a heater part of the time."],
    ["evening_until", "Evening until", "time", ""],
    ["late_evening_kw", "Outage load late evening (kW)", "float", ""],
    ["late_evening_until", "Late evening until", "time", ""],
    ["morning_kw", "Outage load in the morning (kW)", "float", ""],
    ["morning_from", "Morning from", "time", ""],
    ["morning_until", "Morning until", "time", ""],
    ["night_margin", "Night load margin", "float", "Other hours use the house load from history times this (1.25 = +25 %)."],
    ["night_cap_kw", "Night load cap (kW)", "float", ""],
    ["solar_factor", "Share of the forecast trusted", "float", "0.5 = only half of the forecast sun is counted on during an outage."],
    ["max_soc", "Highest reserve (%)", "int", ""],
    ["generator_available", "Generator available", "bool", "With a generator the battery only has to bridge until it starts."],
    ["generator_bridge_hours", "Generator start bridge (hours)", "float", ""],
  ] },
  { key: "floor", title: "Battery floor", fields: [
    ["soc", "Floor (%)", "int", "Every slot the reserve does not protect lets the battery run down to this level."],
    ["grid_charge", "Grid charge at the floor", "bool", ""],
  ] },
  { key: "site", title: "Site and battery", fields: [
    ["latitude", "Latitude", "float", ""],
    ["longitude", "Longitude", "float", ""],
    ["panel_kwp", "Panels (kWp)", "float", ""],
    ["panel_tilt", "Panel tilt (°)", "float", "0 = flat, 90 = vertical."],
    ["panel_azimuth", "Panel azimuth (°)", "float", "0 = south, -90 = east, 90 = west."],
    ["performance_ratio", "Performance ratio", "float", "Share of the ideal output the system delivers (losses, dust, heat)."],
    ["battery_kwh", "Battery capacity (kWh)", "float", ""],
    ["battery_nominal_voltage", "Battery nominal voltage (V)", "float", "Used with the inverter's charge current to estimate charging power."],
    ["min_soc", "Lowest SOC ever written (%)", "int", "Safety floor; keep at or above the BMS shutdown level."],
    ["consumption_days", "Consumption history (days)", "int", "Days of history used to estimate the house load hour by hour."],
    ["fallback_load_kw", "Fallback load (kW)", "float", "Used until there is enough history."],
  ] },
  { key: "tuning", title: "Tuning (rarely changed)", fields: [
    ["check_every_minutes", "Check every (minutes)", "int", "The planner runs this often, each time with a fresh forecast."],
    ["charge_margin", "Charge time margin", "float", "Grid charging starts this much earlier than the bare estimate (1.2 = 20 % earlier)."],
    ["start_step_minutes", "Start time step (minutes)", "int", "Planned starts are rounded down to this step."],
    ["start_tolerance_minutes", "Start tolerance (minutes)", "int", "A planned start on the inverter moves only beyond this."],
    ["soc_tolerance", "Reserve tolerance (points)", "int", "A reserve on the inverter is rewritten only when the new one differs by more."],
    ["solar_ratio_min", "Solar correction minimum", "float", "Today's actual / forecast solar ratio is kept between these bounds."],
    ["solar_ratio_max", "Solar correction maximum", "float", ""],
    ["min_forecast_for_ratio_kwh", "Forecast needed for a correction (kWh)", "float", ""],
    ["fallback_charge_kw", "Charging power if unknown (kW)", "float", "Used when the inverter's charge settings cannot be read."],
    ["manual_max_hours", "Manual charge at most (hours)", "int", ""],
    ["verify_attempts", "Read-back attempts", "int", "After a write the table is read back up to this many times."],
    ["verify_pause_seconds", "Pause between read-backs (s)", "float", ""],
  ] },
];

const form = document.getElementById("settings-form");
let loaded = null;

function input(type, value, name) {
  const common = { name, "data-type": type };
  switch (type) {
    case "bool": return el("input", { ...common, type: "checkbox", checked: Boolean(value) });
    case "int": return el("input", { ...common, type: "number", step: 1, value });
    case "float": return el("input", { ...common, type: "number", step: "any", value });
    case "time": return el("input", { ...common, type: "time", value });
    case "weekdays": return el("span", { ...common }, WEEKDAYS.map((d, i) => el("label", {},
      el("input", { type: "checkbox", value: i, checked: value.includes(i) }), ` ${d} `)));
    default: return el("input", { ...common, type: "text", value: value.join(", ") });
  }
}

function render(settings) {
  form.replaceChildren(...SECTIONS.map((section) => {
    const values = section.key ? settings[section.key] : settings;
    return el("fieldset", {}, el("legend", {}, section.title), section.fields.map(([key, label, type, help]) =>
      el("div", { class: "field" },
        el("label", {}, label),
        input(type, values[key], `${section.key ?? ""}.${key}`),
        help ? el("div", { class: "help" }, help) : null)));
  }));
}

function readValue(node) {
  const type = node.dataset.type;
  if (type === "bool") return node.checked;
  if (type === "int" || type === "float") return Number(node.value);
  if (type === "time") return node.value;
  if (type === "weekdays") return [...node.querySelectorAll("input:checked")].map((c) => Number(c.value));
  return node.value.split(",").map((s) => s.trim()).filter(Boolean);
}

function collect() {
  const result = structuredClone(loaded);
  for (const node of form.querySelectorAll("[data-type]")) {
    const [section, key] = node.getAttribute("name").split(".");
    (section ? result[section] : result)[key] = readValue(node);
  }
  return result;
}

async function load() {
  loaded = await api.get("/api/settings");
  render(loaded);
}

document.getElementById("save-settings").addEventListener("click", (e) => guarded(e.target, async () => {
  loaded = await api.post("/api/settings", collect());
  render(loaded);
  notify("Settings saved. Planner check times are rescheduled.");
}));
document.getElementById("reset-settings").addEventListener("click", () => render(loaded));

load().catch((error) => notify(error.message, "error"));
