import { api } from "./api.js";
import { chargeTiles } from "./charge-settings.js";
import { el, guarded, notify } from "./dom.js";
import { localTime } from "./format.js";
import { readEditor, renderEditor, renderReadOnly } from "./tou-table.js";

const editor = document.getElementById("tou-editor");
const source = document.getElementById("source-select");
const profileSelect = document.getElementById("profile-select");
let state = null;
let profiles = { mode: "off", profiles: [] };

function render() {
  const slots = state[source.value] ?? state.current ?? state.base;
  if (slots) renderEditor(editor, slots);
  renderReadOnly(document.getElementById("tou-current"), state.current);
  document.getElementById("read-at").textContent = state.current_read_at
    ? `last read ${localTime(state.current_read_at)}` : "not read yet";
  document.getElementById("charge-tiles").replaceChildren(...chargeTiles(state.charge_settings));
  document.getElementById("charge-read-at").textContent = state.charge_settings
    ? `read ${localTime(state.charge_settings.read_at)}` : "";
  const toggle = document.getElementById("grid-charge-toggle");
  toggle.disabled = !state.charge_settings;
  toggle.textContent = state.charge_settings?.grid_charge_enabled ? "Turn grid charge off" : "Turn grid charge on";
}

function renderProfiles() {
  const chosen = profileSelect.value;
  profileSelect.replaceChildren(...(profiles.profiles.length
    ? profiles.profiles.map((p) => el("option", { value: p.name, selected: p.name === chosen }, p.name))
    : [el("option", { value: "" }, "No profiles yet")]));
  const locked = profiles.mode !== "off";
  document.getElementById("profile-send").disabled = locked || !profiles.profiles.length;
  document.getElementById("profile-lock").textContent = locked
    ? `Automation is ${profiles.mode}: switch it Off on the Plan page to send a profile.` : "";
}

async function load(path = "/api/time-of-use", body) {
  state = body === undefined ? await api.get(path) : await api.post(path, body);
  render();
  return state;
}

async function loadProfiles() {
  profiles = await api.get("/api/time-of-use/profiles");
  renderProfiles();
}

function selectedProfile() {
  return profiles.profiles.find((p) => p.name === profileSelect.value);
}

source.addEventListener("change", render);
document.getElementById("reload").addEventListener("click", (e) => guarded(e.target, async () => {
  await load("/api/time-of-use/refresh", {});
  notify("Table and charging settings read from the inverter.");
}));
document.getElementById("save-base").addEventListener("click", (e) => guarded(e.target, async () => {
  await load("/api/time-of-use/base", { slots: readEditor(editor) });
  source.value = "base";
  render();
  notify("Base table saved. The planner starts from it at its next check.");
}));
document.getElementById("send").addEventListener("click", (e) => guarded(e.target, async () => {
  if (!window.confirm("Send this table to the inverter now?")) return;
  const result = await load("/api/time-of-use/send", { slots: readEditor(editor) });
  notify(`Inverter: ${result.message}`, result.status === "executed" ? "ok" : "error");
}));
document.getElementById("grid-charge-toggle").addEventListener("click", (e) => guarded(e.target, async () => {
  const enable = !state.charge_settings.grid_charge_enabled;
  if (!window.confirm(`Turn grid charge ${enable ? "on" : "off"} in the inverter now?`)) return;
  state = await api.post("/api/charge-settings/grid-charge", { enabled: enable });
  render();
  notify(`Grid charge ${enable ? "on" : "off"}: ${state.message}`, state.status === "executed" ? "ok" : "error");
}));
document.getElementById("profile-load").addEventListener("click", () => {
  const profile = selectedProfile();
  if (profile) { renderEditor(editor, profile.slots); notify(`Profile "${profile.name}" loaded into the editor (not sent).`); }
});
document.getElementById("profile-save").addEventListener("click", (e) => guarded(e.target, async () => {
  const name = window.prompt("Profile name", selectedProfile()?.name ?? "");
  if (!name) return;
  profiles = await api.post("/api/time-of-use/profiles", { name, slots: readEditor(editor) });
  profileSelect.value = name.trim();
  renderProfiles();
  notify(`Profile "${name.trim()}" saved.`);
}));
document.getElementById("profile-delete").addEventListener("click", (e) => guarded(e.target, async () => {
  const profile = selectedProfile();
  if (!profile || !window.confirm(`Delete profile "${profile.name}"?`)) return;
  profiles = await deleteProfile(profile.name);
  renderProfiles();
}));
document.getElementById("profile-send").addEventListener("click", (e) => guarded(e.target, async () => {
  const profile = selectedProfile();
  if (!profile || !window.confirm(`Send profile "${profile.name}" to the inverter now?`)) return;
  state = await api.post(`/api/time-of-use/profiles/${encodeURIComponent(profile.name)}/apply`);
  render();
  notify(`Profile "${profile.name}": ${state.message}`, state.status === "executed" ? "ok" : "error");
}));

async function deleteProfile(name) {
  return api.delete(`/api/time-of-use/profiles/${encodeURIComponent(name)}`);
}

load().catch((error) => notify(error.message, "error"));
loadProfiles().catch((error) => notify(error.message, "error"));
