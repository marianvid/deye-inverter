// Tiles for the inverter's charging settings (read only).
import { tile } from "./dom.js";

export function chargeTiles(charge, batteryVoltage = 51.2) {
  if (!charge) return [tile("Charging settings", "not read yet", "", "read every 30 minutes")];
  const kw = (charge.grid_charge_current * batteryVoltage / 1000).toFixed(1);
  return [
    tile("Grid charge", charge.grid_charge_enabled ? "On" : "Off", "", "master switch", "--grid"),
    tile("Grid charge current", charge.grid_charge_current, "A", `≈ ${kw} kW`, "--grid"),
    tile("Time of Use", charge.time_of_use_enabled ? "On" : "Off", "", "", "--battery"),
    tile("Work mode", charge.work_mode.replace("Zero export to ", "Zero export → "), "", "", "--battery"),
    tile("Max charge / discharge", `${charge.max_charge_current} / ${charge.max_discharge_current}`, "A", "", "--battery"),
  ];
}
