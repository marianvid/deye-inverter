// Shared by every page: shows the automation mode in the top bar.
import { api } from "./api.js";

const LABELS = { off: "Automation off", "dry-run": "Dry-run", live: "Live" };

export async function refreshModeBadge(mode) {
  const badge = document.getElementById("mode-badge");
  const current = mode ?? (await api.get("/api/settings")).mode;
  badge.textContent = LABELS[current] ?? current;
  badge.className = `mode-badge ${current}`;
}

refreshModeBadge().catch(() => {});
