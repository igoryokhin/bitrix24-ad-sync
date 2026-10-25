import { api, toast } from "./api.js";

let ousCache = null;

export async function renderUsers(panel) {
  panel.innerHTML = `
    <div class="toolbar">
      <input id="u-search" type="text" placeholder="Поиск (логин, ФИО, email)">
      <select id="u-status">
        <option value="">Все статусы</option>
        <option value="active">Активные</option>
        <option value="disabled">Отключённые</option>
      </select>
      <button id="u-search-btn" class="btn">Найти</button>
    </div>
    <div id="u-list"></div>
    <div id="u-detail"></div>
  `;

  const search = async () => {
    const q = panel.querySelector("#u-search").value.trim();
    const status = panel.querySelector("#u-status").value;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    const data = await api(`/users?${params.toString()}`);
    renderList(panel, data.users);
  };

  panel.querySelector("#u-search-btn").addEventListener("click", () => search().catch((e) => toast(e.message, true)));
  panel.querySelector("#u-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") search().catch((err) => toast(err.message, true));
  });

  await search();
}

function renderList(panel, users) {
  const listEl = panel.querySelector("#u-list");
  const rows = users
    .map(
      (u) => `
    <tr data-id="${u.id}">
      <td>${escapeHtml(u.display_name)}</td>
      <td>${escapeHtml(u.login)}</td>
      <td>${escapeHtml(u.department || "")}</td>
      <td>${escapeHtml(u.email || "")}</td>
      <td>${u.disabled ? "отключён" : "активен"}</td>
    </tr>`
    )
    .join("");

  listEl.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Имя</th><th>Логин</th><th>Отдел</th><th>Email</th><th>Статус</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5">Ничего не найдено</td></tr>'}</tbody>
    </table>`;

  listEl.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => openDetail(panel, row.dataset.id).catch((e) => toast(e.message, true)));
  });
}

async function openDetail(panel, userId) {
  const detailEl = panel.querySelector("#u-detail");
  detailEl.innerHTML = "<p>Загрузка…</p>";

  const { user } = await api(`/users/${userId}`);
  if (!ousCache) {
    const { ous } = await api("/ous");
    ousCache = ous;
  }
  const ouOptions = ousCache.map((o) => `<option value="${escapeHtml(o.dn)}">${escapeHtml(o.name)}</option>`).join("");
  const { messages } = await api(`/users/${userId}/messages`);
  const msgRows = messages
    .map(
      (m) => `
    <tr><td>${m.action}</td><td>${m.message_sent ? "отправлено" : "не отправлено"}</td><td>${escapeHtml(m.performed_by)}</td><td>${m.performed_at}</td></tr>`
    )
    .join("");

  detailEl.innerHTML = `
    <div class="detail-card">
      <h3>${escapeHtml(user.display_name)} (${escapeHtml(user.login)})${user.is_admin ? " — администратор домена" : ""}</h3>
      <label>Отдел <input id="d-department" value="${escapeHtml(user.department || "")}"></label>
      <label>Должность <input id="d-title" value="${escapeHtml(user.title || "")}"></label>
      <label>Email <input id="d-email" value="${escapeHtml(user.email || "")}"></label>
      <div class="actions">
        <button id="d-save" class="btn">Сохранить</button>
        <button id="d-toggle" class="btn">${user.disabled ? "Включить" : "Отключить"}</button>
        <button id="d-reset" class="btn btn-danger">Сбросить пароль и отправить</button>
        <button id="d-resend" class="btn">Напомнить текущий пароль</button>
      </div>
      <div class="move-row">
        <select id="d-ou">${ouOptions}</select>
        <button id="d-move" class="btn">Переместить</button>
      </div>
      <h4>История сообщений</h4>
      <table class="data-table">
        <thead><tr><th>Действие</th><th>Отправка</th><th>Кто</th><th>Когда</th></tr></thead>
        <tbody>${msgRows || '<tr><td colspan="4">Нет записей</td></tr>'}</tbody>
      </table>
    </div>
  `;

  detailEl.querySelector("#d-save").addEventListener("click", async () => {
    try {
      await api(`/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({
          department: detailEl.querySelector("#d-department").value,
          title: detailEl.querySelector("#d-title").value,
          email: detailEl.querySelector("#d-email").value,
        }),
      });
      toast("Сохранено");
    } catch (e) {
      toast(e.message, true);
    }
  });

  detailEl.querySelector("#d-toggle").addEventListener("click", async () => {
    try {
      const action = user.disabled ? "enable" : "disable";
      await api(`/users/${userId}/${action}`, { method: "POST" });
      toast("Готово");
      openDetail(panel, userId);
    } catch (e) {
      toast(e.message, true);
    }
  });

  detailEl.querySelector("#d-reset").addEventListener("click", async () => {
    if (!confirm("Сбросить пароль и отправить новые учётные данные в Bitrix24?")) return;
    try {
      const res = await api(`/users/${userId}/reset-password`, { method: "POST" });
      toast(
        res.message_sent
          ? "Пароль сброшен, сообщение отправлено"
          : "Пароль сброшен, но сообщение НЕ отправлено (нет B24_UID или тестовый режим)"
      );
      openDetail(panel, userId);
    } catch (e) {
      toast(e.message, true);
    }
  });

  detailEl.querySelector("#d-resend").addEventListener("click", async () => {
    try {
      const res = await api(`/users/${userId}/resend`, { method: "POST" });
      toast(res.message_sent ? "Отправлено (пароль не менялся)" : "Пароль не менялся, но сообщение НЕ отправлено");
      openDetail(panel, userId);
    } catch (e) {
      if (e.status === 404 && e.data?.error === "no_stored_password") {
        toast("Для этого пользователя ещё нет сохранённого пароля — сначала используйте «Сбросить пароль и отправить»", true);
      } else {
        toast(e.message, true);
      }
    }
  });

  detailEl.querySelector("#d-move").addEventListener("click", async () => {
    const target = detailEl.querySelector("#d-ou").value;
    try {
      await api(`/users/${userId}/move`, { method: "POST", body: JSON.stringify({ target_ou: target }) });
      toast("Перемещено");
    } catch (e) {
      toast(e.message, true);
    }
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
