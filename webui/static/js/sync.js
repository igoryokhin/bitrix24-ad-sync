import { api, toast } from "./api.js";

export async function renderSync(panel) {
  panel.innerHTML = `
    <div class="actions">
      <button id="s-full" class="btn">Запустить Full Sync</button>
      <button id="s-delta" class="btn">Запустить Delta Sync</button>
    </div>
    <div id="s-runs"></div>
  `;

  panel.querySelector("#s-full").addEventListener("click", () => trigger(panel, "full"));
  panel.querySelector("#s-delta").addEventListener("click", () => trigger(panel, "delta"));

  await loadRuns(panel);
}

async function trigger(panel, type) {
  try {
    await api("/sync/trigger", { method: "POST", body: JSON.stringify({ type }) });
    toast("Запуск начат");
    await loadRuns(panel);
  } catch (e) {
    if (e.status === 409) toast("Такой синк уже выполняется", true);
    else toast(e.message, true);
  }
}

async function loadRuns(panel) {
  const { runs } = await api("/sync/runs");
  const rows = runs
    .map(
      (r) => `
    <tr>
      <td>${r.run_type}</td><td>${r.status}</td><td>${r.triggered_by}</td>
      <td>${r.started_at || ""}</td><td>${r.finished_at || ""}</td>
      <td><a href="#" data-id="${r.id}" class="view-log">лог</a></td>
    </tr>`
    )
    .join("");

  const runsEl = panel.querySelector("#s-runs");
  runsEl.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Тип</th><th>Статус</th><th>Кем</th><th>Начало</th><th>Конец</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6">Пока нет запусков</td></tr>'}</tbody>
    </table>
    <pre id="s-log"></pre>`;

  runsEl.querySelectorAll(".view-log").forEach((a) => {
    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const log = await fetch(`/api/sync/runs/${a.dataset.id}/log`, { credentials: "same-origin" }).then((r) => r.text());
      runsEl.querySelector("#s-log").textContent = log;
    });
  });
}
