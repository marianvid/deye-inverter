import { api } from "./api.js";
import { draw, series } from "./charts.js";
import { notify, tile } from "./dom.js";
import { num } from "./format.js";

function dayLabel(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

function hourKey(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { weekday: "short" })} ${String(d.getHours()).padStart(2, "0")}:00`;
}

function render(data) {
  document.getElementById("day-tiles").replaceChildren(...data.days.map((d) => tile(
    dayLabel(d.day), num(d.forecast_kwh), "kWh forecast",
    d.actual_kwh === null ? "" : `actual ${num(d.actual_kwh)} kWh`, "--forecast")));
  const actual = new Map(data.actual_hours.map((h) => [hourKey(h.hour_end), h.solar_kwh]));
  const daylight = data.hours.filter((h) => h.solar_kwh > 0 || actual.has(hourKey(h.hour_end)));
  draw("hourly-chart", {
    type: "bar",
    data: {
      labels: daylight.map((h) => hourKey(h.hour_end)),
      datasets: [
        series("Forecast kWh", daylight.map((h) => h.solar_kwh), "--forecast"),
        series("Actual kWh", daylight.map((h) => actual.get(hourKey(h.hour_end)) ?? null), "--solar",
          { type: "line", pointRadius: 2 }),
      ],
    },
    options: { scales: { x: {}, y: { title: { display: true, text: "kWh per hour" } } } },
  });
}

api.get("/api/forecast").then(render).catch((error) => notify(error.message, "error"));
