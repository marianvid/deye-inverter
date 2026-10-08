import { api } from "./api.js";
import { chargeTiles } from "./charge-settings.js";
import { draw, series } from "./charts.js";
import { notify, tile } from "./dom.js";
import { age, isoDate, kw, num } from "./format.js";

const REFRESH_MS = 60_000;

function powerTiles(r) {
  return [
    tile("Solar", kw(r.solar_power), "kW", "", "--solar"),
    tile("House load", kw(r.load_power), "kW", "", "--load"),
    tile("Backup output", kw(r.backup_load_power), "kW", "", "--backup"),
    tile("Grid", kw(r.grid_power), "kW", "", "--grid"),
  ];
}

function batteryTiles(r, settings) {
  const tiles = [
    tile("Battery power", kw(r.battery_power), "kW", "", "--battery"),
    tile("Voltage", num(r.battery_voltage, 2), "V", "", "--battery"),
    tile("Temperature", num(r.battery_temperature), "°C", "", "--battery"),
  ];
  if (settings) {
    tiles.push(tile("Shutdown / low", `${settings.shutdown_soc} / ${settings.low_soc}`, "%",
      `max charge ${settings.max_charge_current} A`, "--battery"));
  }
  return tiles;
}

function todayTiles(r) {
  return [
    tile("Solar", num(r.solar_today), "kWh", "", "--solar"),
    tile("Consumption", num(r.load_today), "kWh", "", "--load"),
    tile("Bought from grid", num(r.grid_bought_today), "kWh", "", "--grid"),
    tile("Battery in / out", `${num(r.battery_charged_today)} / ${num(r.battery_discharged_today)}`, "kWh", "", "--battery"),
  ];
}

function render(data) {
  const r = data.reading;
  document.getElementById("data-age").textContent = r
    ? `Data from the inverter: ${age(data.age_seconds)} (DeyeCloud refreshes every 3–5 minutes).`
    : "No data yet: the first reading arrives within a few minutes.";
  if (!r) return;
  document.getElementById("power-tiles").replaceChildren(...powerTiles(r));
  document.getElementById("battery-tiles").replaceChildren(...batteryTiles(r, data.battery_settings));
  document.getElementById("charge-tiles").replaceChildren(...chargeTiles(data.charge_settings));
  document.getElementById("today-tiles").replaceChildren(...todayTiles(r));
  document.getElementById("soc-fill").style.width = `${r.battery_soc}%`;
  document.getElementById("soc-label").textContent = `${num(r.battery_soc, 0)} %`;
}

function renderChart(day) {
  draw("today-chart", {
    type: "line",
    data: {
      labels: day.times,
      datasets: [
        series("Solar kW", day.solar_power.map((w) => w / 1000), "--solar"),
        series("Load kW", day.load_power.map((w) => w / 1000), "--load"),
        series("SOC %", day.battery_soc, "--soc", { yAxisID: "soc", borderDash: [4, 3] }),
      ],
    },
    options: { scales: { y: { title: { display: true, text: "kW" } },
      soc: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false } } } },
  });
}

async function refresh() {
  try {
    render(await api.get("/api/now"));
    renderChart(await api.get(`/api/history/day?day=${isoDate(new Date())}`));
  } catch (error) {
    notify(error.message, "error");
  }
}

refresh();
window.setInterval(refresh, REFRESH_MS);
