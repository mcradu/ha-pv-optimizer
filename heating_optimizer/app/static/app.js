/* Heating Optimizer Ingress UI. All untrusted HA values use textContent. */
"use strict";
const byId = id => document.getElementById(id);
const number = (value, unit = "", digits = 1) =>
  value === null || value === undefined || Number.isNaN(Number(value))
    ? "—" : Number(value).toLocaleString("ro-RO", {
        minimumFractionDigits: digits, maximumFractionDigits: digits
      }) + (unit ? " " + unit : "");
const write = (id, value) => { const node = byId(id); if (node) node.textContent = value ?? "—"; };
const fmtDate = value => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ro-RO");
};
const booleanLabel = value => value ? "Da" : "Nu";
const radio = document.querySelectorAll(".tabs button");
radio.forEach(btn => btn.addEventListener("click", () => {
  radio.forEach(item => item.classList.toggle("selected", item === btn));
  document.querySelectorAll(".panel").forEach(panel =>
    panel.classList.toggle("open", panel.id === btn.dataset.tab)
  );
}));
let isEditing = false;
let firstLoad = true;
const weekdays = [
  ["monday", "Luni"], ["tuesday", "Marți"], ["wednesday", "Miercuri"],
  ["thursday", "Joi"], ["friday", "Vineri"], ["saturday", "Sâmbătă"], ["sunday", "Duminică"]
];
const scheduleFields = byId("schedule-fields");
for (const [day, name] of weekdays) {
  const label = document.createElement("label");
  label.textContent = name;
  const field = document.createElement("input");
  field.type = "time"; field.name = "schedule_" + day; field.required = true;
  label.appendChild(field); scheduleFields.appendChild(label);
}
const form = byId("settings-form");
form.addEventListener("input", () => { isEditing = true; });
const json = async url => {
  const res = await fetch(url, {cache: "no-store"});
  let payload;
  try { payload = await res.json(); } catch { throw Error("Răspuns invalid"); }
  if (!res.ok) throw Error(payload.error || "HTTP " + res.status);
  return payload;
};
async function loadSettings() {
  const options = await json("api/settings");
  if (isEditing) return;
  for (const node of form.querySelectorAll("[name]")) {
    if (node.name.startsWith("schedule_")) {
      node.value = options.morning_schedule?.[node.name.slice(9)] ?? "";
    } else if (node.type === "checkbox") {
      node.checked = Boolean(options[node.name]);
    } else if (node.name in options) {
      node.value = String(options[node.name]);
    }
  }
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  const button = byId("save-settings");
  button.disabled = true;
  const message = byId("settings-message");
  message.classList.remove("error");
  write("settings-message", "Se salvează…");
  const updates = {morning_schedule: {}};
  for (const node of form.querySelectorAll("[name]")) {
    if (node.name.startsWith("schedule_")) {
      updates.morning_schedule[node.name.slice(9)] = node.value;
    } else if (node.type === "checkbox") {
      updates[node.name] = node.checked;
    } else if (node.type === "number") {
      updates[node.name] = Number(node.value);
    }
  }
  try {
    const response = await fetch("api/settings", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(updates)
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw Error(payload.error || "HTTP " + response.status);
    write("settings-message", "Setări salvate. Simularea a fost resetată.");
    isEditing = false;
  } catch (err) {
    message.classList.add("error");
    write("settings-message", String(err.message || err));
  } finally {
    button.disabled = false;
  }
});
const decisionBadge = (id, active, isShadow = false) => {
  const item = byId(id);
  item.textContent = (isShadow ? "Simulare: " : "Actual: ") + (
    active ? "încălzește" : "oprit"
  );
  item.className = "pill " + (active ? "good" : "neutral");
};
function render(result) {
  const decision = result.decision;
  const health = result.health;
  const light = byId("health-indicator");
  light.className = "light " + (health === "healthy" ? "good" : "bad");
  write("health-label", health === "healthy" ? "Conectat" : health);
  write("last-refresh", "Actualizat: " + fmtDate(result.last_update));
  write("diag-state", result.state);
  write("diag-time", fmtDate(result.last_update));
  write("diag-entities", (result.available_entities ?? "—") + " / " + (result.configured_entities ?? "—"));
  const errors = byId("diag-error");
  errors.hidden = !result.errors?.length;
  errors.textContent = (result.errors || []).join("; ");
  if (!decision) return;
  for (const [zone, short] of [["down", "down"], ["up", "up"]]) {
    const d = decision.zones?.[zone];
    if (!d) continue;
    write(short + "-temperature", number(d.room_temperature_c, "°C"));
    write(short + "-target", number(d.target_temperature_c, "°C"));
    decisionBadge(short + "-actual", d.observed_hvac_mode === "heat");
    decisionBadge(short + "-simulated", d.simulated_on, true);
    write(short + "-reasons", (d.reasons || []).join(" · ") || "Fără restricții");
  }
  const battery = decision.battery || {};
  write("battery-soc", number(battery.soc, "%", 0));
  byId("battery-fill").style.width = Math.max(0, Math.min(100, battery.soc || 0)) + "%";
  write("battery-target", battery.sunset_target_reachable === null
    ? "Prognoză indisponibilă" : battery.sunset_target_reachable
    ? "Țintă la apus: realizabilă" : "Țintă la apus: nefavorabilă");
  write("battery-headroom", "Surplus până la apus: " + number(battery.headroom_kwh, "kWh"));
  write("puffer-temperature", number(decision.boiler?.puffer_temperature_c, "°C"));
  write("boiler-state", decision.boiler?.observed_switch || "—");
  write("ufh-state", decision.ufh?.observed_switch || "—");
  const morning = decision.morning || {};
  write("morning-time", morning.schedule_target || "—");
  write("morning-start", morning.predicted_start
    ? new Date(morning.predicted_start).toLocaleTimeString("ro-RO", {hour: "2-digit", minute: "2-digit"})
    : "—");
  write("morning-reserve", number(morning.reserve_soc, "%", 0));
  write("morning-budget", number(morning.heating_energy_budget_kwh, "kWh", 2));
  write("morning-fallback", booleanLabel(morning.comfort_fallback));
  write("morning-eligible", booleanLabel(morning.budget_ok));
  write("forecast-stable", number(battery.pv_stable_seconds, "sec", 0));
  const money = n => n == null ? "—" : number(n, "RON", 2);
  const f = decision.financial || {};
  write("saving-day", money(f.financial_day));
  write("saving-week", money(f.financial_week));
  write("saving-month", money(f.financial_month));
  write("cost-grid-day", money(f.all_grid_day));
  write("cost-grid-week", money(f.all_grid_week));
  write("cost-grid-month", money(f.all_grid_month));
  write("heat-cost", money(f.heat_cost));
  write("energy-headroom", number(battery.headroom_kwh, "kWh", 2));
  write("energy-shortfall", number(battery.sunset_shortfall_kwh, "kWh", 2));
  write("energy-surplus", number(battery.surplus_w, "W", 0));
  const events = byId("event-list");
  events.replaceChildren();
  if (!result.events?.length) {
    events.textContent = "Nu există încă evenimente.";
  } else {
    for (const event of [...result.events].reverse().slice(0, 30)) {
      const item = document.createElement("div"); item.className = "event";
      const heading = document.createElement("strong");
      heading.textContent = "Parter: " + event.down + " | Etaj: " + event.up;
      const when = document.createElement("small");
      when.textContent = fmtDate(event.timestamp) + " · doar simulare";
      item.append(heading, when); events.appendChild(item);
    }
  }
  const table = byId("entities-list"); table.replaceChildren();
  for (const row of Object.values(decision.observations || {})) {
    const tr = document.createElement("tr");
    for (const data of [row.entity, row.value ?? "indisponibil", fmtDate(row.updated)]) {
      const cell = document.createElement("td");
      cell.textContent = String(data); tr.appendChild(cell);
    }
    table.appendChild(tr);
  }
}
async function refresh() {
  try {
    const status = await json("api/status");
    render(status);
    if (firstLoad) {
      firstLoad = false;
      await loadSettings();
    }
  } catch (err) {
    byId("health-indicator").className = "light bad";
    write("health-label", "Conexiune indisponibilă");
    write("last-refresh", "Eroare: " + String(err.message || err));
  }
}
refresh();
setInterval(refresh, 15000);
