import asyncio

import db as botdb
from services.password_reset import do_password_reset_batch, do_resend_batch
from handlers.action_choice import ACTION_RESET, ACTION_RESEND


def _actor(update):
    user = update.effective_user
    if not user:
        return "tg:unknown"
    uname = f"@{user.username}" if user.username else ""
    return f"tg:{user.id}{uname}"


def _run_batch(targets, actor, template, action):
    conn = botdb.get_db()
    try:
        fn = do_password_reset_batch if action == ACTION_RESET else do_resend_batch
        return fn(conn, targets, actor, template)
    finally:
        conn.close()


async def run_broadcast(update, context):
    targets = context.user_data.get("targets", [])
    template = context.user_data.get("template", "ad")
    action = context.user_data.get("action", ACTION_RESET)
    actor = _actor(update)

    msg = update.callback_query.message if update.callback_query else update.message
    await msg.reply_text(f"Начинаю рассылку: {len(targets)} получателей…")

    results = await asyncio.to_thread(_run_batch, targets, actor, template, action)

    ok = sum(1 for r in results if r.get("success") and r.get("message_sent"))
    not_sent = sum(1 for r in results if r.get("success") and not r.get("message_sent"))
    failed = sum(1 for r in results if not r.get("success"))

    if action == ACTION_RESEND:
        fail_label = "Нет сохранённого пароля / ошибка"
        success_label = "Успешно (сообщение отправлено, пароль НЕ менялся)"
    else:
        fail_label = "Ошибка сброса пароля в AD"
        success_label = "Успешно (пароль сброшен, сообщение отправлено)"

    summary = (
        f"Готово.\n"
        f"Всего: {len(results)}\n"
        f"{success_label}: {ok}\n"
        f"{fail_label}: {failed}\n"
        f"Выполнено, но сообщение НЕ отправлено: {not_sent}"
    )
    await msg.reply_text(summary)

    from handlers.menu import send_scope_menu
    return await send_scope_menu(msg, context)
