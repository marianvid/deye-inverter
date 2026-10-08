// Chart.js helpers: colours come from the CSS variables, so light and dark themes match.

const charts = new Map();

export function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function series(label, data, colorVar, extra = {}) {
  const color = cssColor(colorVar);
  return { label, data, borderColor: color, backgroundColor: color, borderWidth: 2,
    pointRadius: 0, tension: 0.25, ...extra };
}

export function draw(canvasId, config) {
  charts.get(canvasId)?.destroy();
  const text = cssColor("--muted");
  const grid = cssColor("--border");
  const axes = config.options?.scales ?? {};
  for (const axis of Object.values(axes)) {
    axis.ticks = { color: text, ...(axis.ticks ?? {}) };
    axis.grid = { color: grid, ...(axis.grid ?? {}) };
  }
  const chart = new window.Chart(document.getElementById(canvasId), {
    ...config,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } } },
      ...config.options,
    },
  });
  charts.set(canvasId, chart);
  return chart;
}
