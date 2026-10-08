// Renders a Time of Use table, read-only or as an editor.
import { el, fillTable } from "./dom.js";

const HEADERS = ["Start", "SOC %", "Power W", "Voltage", "Grid charge", "Generator"];

export function renderReadOnly(table, slots, changed = []) {
  if (!slots) {
    table.replaceChildren(el("tbody", {}, el("tr", {}, el("td", {}, "Not read yet."))));
    return;
  }
  fillTable(table, HEADERS, slots.map((s, i) => {
    const cls = changed.includes(i) ? "changed" : undefined;
    return [s.start, s.soc, s.power, s.voltage, s.grid_charge ? "on" : "off",
      s.generator_charge ? "on" : "off"].map((v) => el("td", { class: cls }, v));
  }));
}

export function renderEditor(table, slots) {
  fillTable(table, HEADERS, slots.map((s) => [
    el("input", { type: "time", value: s.start, "data-field": "start" }),
    el("input", { type: "number", min: 0, max: 100, value: s.soc, "data-field": "soc" }),
    el("input", { type: "number", min: 0, step: 100, value: s.power, "data-field": "power" }),
    el("input", { type: "number", step: 0.1, value: s.voltage, "data-field": "voltage" }),
    el("input", { type: "checkbox", checked: s.grid_charge, "data-field": "grid_charge" }),
    el("input", { type: "checkbox", checked: s.generator_charge, "data-field": "generator_charge" }),
  ]));
}

export function readEditor(table) {
  return [...table.querySelectorAll("tbody tr")].map((row) => {
    const value = (field) => row.querySelector(`[data-field="${field}"]`);
    return {
      start: value("start").value,
      soc: Number(value("soc").value),
      power: Number(value("power").value),
      voltage: Number(value("voltage").value),
      grid_charge: value("grid_charge").checked,
      generator_charge: value("generator_charge").checked,
    };
  });
}
