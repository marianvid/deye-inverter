import { api } from "./api.js";
import { draw, series } from "./charts.js";
import { fillTable, notify, tile } from "./dom.js";
import { isoDate, num } from "./format.js";

const state = { period: "day", day: isoDate(new Date()) };
const anchor = document.getElementById("anchor");

function totalsTiles(t) {
  const pct = (part) => (t.consumption > 0 ? `${num((part / t.consumption) * 100, 0)} % of consumption` : "");
  return [
    tile("Consumed", num(t.consumption), "kWh", "", "--load"),
    tile("From solar", num(t.from_solar), "kWh", pct(t.from_solar) + " (directly or via battery)", "--solar"),
    tile("From grid", num(t.from_grid), "kWh", pct(t.from_grid), "--grid"),
    tile("Solar produced", num(t.solar), "kWh", "", "--solar"),
    tile("Battery charged", num(t.charged), "kWh", "", "--battery"),
    tile("Battery discharged", num(t.discharged), "kWh", "", "--battery"),
  ];
}

function renderShare(t) {
  const box = document.getElementById("share");
  const legend = document.getElementById("share-legend");
  box.hidden = !(t.consumption > 0);
  if (box.hidden) { legend.textContent = ""; return; }
  const solar = (t.from_solar / t.consumption) * 100;
  document.getElementById("share-solar").style.width = `${solar}%`;
  document.getElementById("share-grid").style.width = `${100 - solar}%`;
  legend.textContent = `Self-sufficiency ${num(solar, 0)} %: share of consumption that did not come from the grid.`;
}

function curveChart(curve) {
  const kwOf = (values) => values.map((w) => w / 1000);
  draw("stats-chart", {
    type: "line",
    data: {
      labels: curve.times,
      datasets: [
        series("Solar", kwOf(curve.solar_power), "--solar"),
        series("Consumption", kwOf(curve.load_power), "--load"),
        series("Grid", kwOf(curve.grid_power), "--grid"),
        series("Battery", kwOf(curve.battery_power), "--battery"),
        series("SOC %", curve.battery_soc, "--soc", { yAxisID: "soc", borderDash: [4, 3] }),
      ],
    },
    options: { scales: { x: { ticks: { maxTicksLimit: 14 } }, y: { title: { display: true, text: "kW" } },
      soc: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false } } } },
  });
}

function barChart(data) {
  const labels = data.buckets.map((b) => b.label);
  const datasets = [
    series("From solar", data.buckets.map((b) => b.from_solar), "--solar", { stack: "used" }),
    series("From grid", data.buckets.map((b) => b.from_grid), "--grid", { stack: "used" }),
    series("Solar produced", data.buckets.map((b) => b.solar), "--forecast", { type: "line", pointRadius: 2 }),
  ];
  const scales = { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "kWh" } } };
  if (data.soc_by_day) {
    const byDay = new Map(data.soc_by_day.map((s) => [s.day, s]));
    datasets.push(series("SOC min %", labels.map((l) => byDay.get(l)?.min ?? null), "--soc", { type: "line", yAxisID: "soc", borderDash: [4, 3] }));
    datasets.push(series("SOC max %", labels.map((l) => byDay.get(l)?.max ?? null), "--soc", { type: "line", yAxisID: "soc" }));
    scales.soc = { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false } };
  }
  draw("stats-chart", { type: "bar", data: { labels, datasets }, options: { scales } });
}

function renderTable(data) {
  const show = data.buckets.length > 0;
  document.getElementById("table-title").hidden = !show;
  fillTable(document.getElementById("buckets"), show ? ["Period", "Consumed", "From solar", "From grid", "Self-sufficiency", "Solar produced", "Battery in", "Battery out"] : [],
    data.buckets.slice().reverse().map((b) => [b.label, num(b.consumption), num(b.from_solar), num(b.from_grid),
      b.self_sufficiency === null ? "–" : `${num(b.self_sufficiency, 0)} %`, num(b.solar), num(b.charged), num(b.discharged)]));
}

function renderCounters(counters) {
  const section = document.getElementById("counters");
  section.hidden = !counters;
  if (counters) document.getElementById("counter-tiles").replaceChildren(...totalsTiles(counters));
}

function render(data) {
  document.getElementById("period-label").textContent = data.label;
  document.getElementById("prev").disabled = !data.previous;
  document.getElementById("next").disabled = !data.next;
  document.getElementById("prev").dataset.day = data.previous ?? "";
  document.getElementById("next").dataset.day = data.next ?? "";
  document.getElementById("coverage").textContent = data.period === "day" ? "" : `${data.days_with_data} days with data`;
  anchor.hidden = data.period === "lifetime";
  document.getElementById("totals").replaceChildren(...totalsTiles(data.totals));
  renderShare(data.totals);
  if (data.curve) curveChart(data.curve); else barChart(data);
  renderTable(data);
  renderCounters(data.inverter_counters);
  for (const button of document.querySelectorAll("#period-switch button")) {
    button.classList.toggle("active", button.dataset.period === data.period);
  }
}

async function load() {
  anchor.value = state.day;
  try {
    render(await api.get(`/api/statistics?period=${state.period}&day=${state.day}`));
  } catch (error) {
    notify(error.message, "error");
  }
}

for (const button of document.querySelectorAll("#period-switch button")) {
  button.addEventListener("click", () => { state.period = button.dataset.period; load(); });
}
for (const id of ["prev", "next"]) {
  document.getElementById(id).addEventListener("click", (e) => {
    if (e.target.dataset.day) { state.day = e.target.dataset.day; load(); }
  });
}
anchor.addEventListener("change", () => { if (anchor.value) { state.day = anchor.value; load(); } });
load();
