// Number and time formatting for the interface.

export function kw(watts) {
  return watts === null || watts === undefined ? "–" : (watts / 1000).toFixed(2);
}

// DeyeCloud reports battery power positive while discharging, negative while charging.
// Shown as a size plus a word, so no sign has to be decoded.
export function batteryFlow(watts) {
  if (watts === null || watts === undefined) return { value: "–", direction: "" };
  const direction = watts < -20 ? "charging" : watts > 20 ? "discharging" : "idle";
  return { value: kw(Math.abs(watts)), direction };
}

export function num(value, digits = 1) {
  return value === null || value === undefined ? "–" : Number(value).toFixed(digits);
}

export function localTime(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}

export function age(seconds) {
  if (seconds === null || seconds === undefined) return "no data yet";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

export function isoDate(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}
