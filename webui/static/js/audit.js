import { api } from "./api.js";

export async function renderAudit(panel) {
  const { entries } = await api("/audit");
  const rows = entries
    .map(
      (e) => `
    <tr>
      <td>${e.created_at}</td><td>${escapeHtml(e.actor)}</td><td>${e.action}</td>
      <td>${escapeHtml(e.target || "")}</td><td>${e.outcome}</td><td>${escapeHtml(e.detail || "")}</td>
    </tr>`
    )
    .join("");

  panel.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Цель</th><th>Итог</th><th>Детали</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6">Пусто</td></tr>'}</tbody>
    </table>`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
