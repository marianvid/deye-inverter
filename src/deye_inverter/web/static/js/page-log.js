import { api } from "./api.js";
import { el, fillTable, notify } from "./dom.js";
import { localTime } from "./format.js";

const kind = document.getElementById("kind-select");

function details(entry) {
  if (entry.kind === "decision") return entry.rules.map((r) => r.summary).join(" ") || entry.message;
  if (entry.kind === "command" || entry.kind === "setting") return `${entry.reason}: ${entry.message}${entry.order_id ? ` (order ${entry.order_id})` : ""}`;
  return `${entry.job ?? ""}: ${entry.message ?? ""}`;
}

async function load() {
  try {
    const entries = await api.get(`/api/log?limit=200${kind.value ? `&kind=${kind.value}` : ""}`);
    fillTable(document.getElementById("log-table"), ["When", "Kind", "Status", "Details"],
      entries.map((e) => [localTime(e.at), e.kind, el("span", { class: `status ${e.status}` }, e.status), details(e)]));
  } catch (error) {
    notify(error.message, "error");
  }
}

kind.addEventListener("change", load);
load();
