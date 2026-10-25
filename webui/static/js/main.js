import { api, toast } from "./api.js";
import { renderDashboard } from "./dashboard.js";
import { renderUsers } from "./users.js";
import { renderSync } from "./sync.js";
import { renderSettings } from "./settings.js";
import { renderAudit } from "./audit.js";

const renderers = {
  dashboard: renderDashboard,
  users: renderUsers,
  sync: renderSync,
  settings: renderSettings,
  audit: renderAudit,
};

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  const panel = document.getElementById(`tab-${name}`);
  renderers[name](panel).catch((e) => toast(e.message, true));
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

async function init() {
  try {
    const me = await api("/me");
    document.getElementById("user-name").textContent = `${me.name} (${me.method === "oidc" ? "Keycloak" : "локальный"})`;
  } catch (e) {
    return;
  }
  activateTab("dashboard");
}

init();
