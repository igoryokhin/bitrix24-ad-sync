import { api, toast } from "./api.js";

const LABELS = {
  TEST_RECIPIENT_ID: "Тестовый получатель (Bitrix UID)",
  PASSWORD_LENGTH: "Длина генерируемого пароля",
  DISABLED_RETENTION_DAYS: "Хранить отключённых, дней",
  ADMIN_GROUP_NAME: "Группа администраторов домена",
  INSTRUCTION_URL: "Ссылка на инструкцию",
};

export async function renderSettings(panel) {
  const data = await api("/settings");

  const editableRows = Object.entries(data.editable)
    .map(([k, v]) => `<label>${LABELS[k] || k}<input data-key="${k}" value="${escapeAttr(v ?? "")}"></label>`)
    .join("");

  const readonlyRows = Object.entries(data.readonly)
    .map(([k, v]) => `<div class="readonly-row"><span>${k}</span><code>${escapeHtml(v ?? "")}</code></div>`)
    .join("");

  panel.innerHTML = `
    <form id="settings-form">
      <h3>Редактируемые</h3>
      ${editableRows}
      <button type="submit" class="btn">Сохранить</button>
    </form>
    <p class="banner">
      Изменение вступит в силу для автоматических (cron) синхронизаций после ручного
      <code>docker compose restart ad-sync</code>; ручные запуски синка из этой панели уже используют новое значение.
    </p>
    <h3>Только для чтения (правится вручную в .env на сервере)</h3>
    ${readonlyRows}
  `;

  panel.querySelector("#settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const changes = {};
    panel.querySelectorAll("#settings-form input[data-key]").forEach((el) => {
      changes[el.dataset.key] = el.value;
    });
    try {
      await api("/settings", { method: "POST", body: JSON.stringify(changes) });
      toast("Настройки сохранены");
    } catch (err) {
      toast(err.message, true);
    }
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}
