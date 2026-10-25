import { api } from "./api.js";

export async function renderDashboard(panel) {
  panel.innerHTML = "<p>Загрузка…</p>";
  const data = await api("/dashboard");

  const runsRows = (data.last_runs || [])
    .map(
      (r) =>
        `<tr><td>${r.run_type}</td><td>${r.status}</td><td>${r.started_at || ""}</td><td>${r.finished_at || ""}</td></tr>`
    )
    .join("");

  panel.innerHTML = `
    <div class="cards">
      <div class="card"><div class="card-value">${data.ad_users_total ?? "—"}</div><div class="card-label">Пользователей в AD</div></div>
      <div class="card"><div class="card-value">${data.ad_users_disabled ?? "—"}</div><div class="card-label">Отключено в AD</div></div>
      <div class="card"><div class="card-value">${data.bitrix_active ?? "—"}</div><div class="card-label">Активных в Bitrix24</div></div>
      <div class="card"><div class="card-value">${data.bitrix_inactive ?? "—"}</div><div class="card-label">Уволенных в Bitrix24</div></div>
    </div>
    ${data.ad_error ? `<p class="error">AD недоступен: ${data.ad_error}</p>` : ""}
    ${data.bitrix_error ? `<p class="error">Bitrix24 недоступен: ${data.bitrix_error}</p>` : ""}
    <h3>Последние запуски (инициированные из панели)</h3>
    <table class="data-table">
      <thead><tr><th>Тип</th><th>Статус</th><th>Начало</th><th>Конец</th></tr></thead>
      <tbody>${runsRows || '<tr><td colspan="4">Пока не было запусков из панели</td></tr>'}</tbody>
    </table>
    <p class="hint" style="margin-top:8px;color:var(--text-dim);font-size:12px;">
      Статус cron-запусков внутри контейнера ad-sync здесь не отображается (см. вкладку «Синхронизация» для ручных запусков).
    </p>
  `;
}
