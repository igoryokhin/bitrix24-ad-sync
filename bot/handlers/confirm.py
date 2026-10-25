import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler

from auth import restricted
from state import CONFIRMING, AWAITING_CONFIRM_PHRASE
import queries
import db as botdb
from handlers.menu import SCOPE_ALL, SCOPE_NOT_RECEIVED, SCOPE_BY_NAME
from handlers.action_choice import ACTION_RESET, ACTION_LABELS

CONFIRM_PHRASE = "ПОДТВЕРЖДАЮ"


def _resolve_targets_sync(scope, base_dn):
    """Синхронная часть — вызывается через asyncio.to_thread."""
    if scope == SCOPE_BY_NAME:
        return None  # targets уже готовы заранее, см. show_confirm
    users = queries.get_active_users(base_dn, None)
    if scope == SCOPE_NOT_RECEIVED:
        conn = botdb.get_db()
        try:
            users = queries.get_not_received(conn, users)
        finally:
            conn.close()
    return [u["dn"] for u in users]


async def _reply(update, text, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def show_confirm(update, context):
    scope = context.user_data.get("scope")
    base_dn = context.user_data.get("base_dn")

    if scope == SCOPE_BY_NAME:
        targets = context.user_data.get("targets", [])
    else:
        await _reply(update, "Считаю получателей…")
        try:
            targets = await asyncio.to_thread(_resolve_targets_sync, scope, base_dn)
        except Exception as e:
            await _reply(update, f"Ошибка при получении списка пользователей: {e}")
            return ConversationHandler.END

    context.user_data["targets"] = targets
    scope_label = context.user_data.get("scope_label", scope)
    template_label = "Почта" if context.user_data.get("template") == "mail" else "AD"
    action = context.user_data.get("action", ACTION_RESET)
    action_label = ACTION_LABELS.get(action, action)

    header = (
        f"Охват: {scope_label}\nДействие: {action_label}\nШаблон: {template_label}\n"
        f"Получателей: {len(targets)}\n\n"
    )

    if not targets:
        await _reply(update, header + "Получателей нет, рассылка не требуется.")
        return ConversationHandler.END

    # Фраза-подтверждение нужна только для самой необратимой комбинации —
    # сброс пароля ВСЕМ сразу. "Напомнить" пароль в AD не меняет, поэтому
    # для него даже в охвате "всем" хватает обычной кнопки.
    if scope == SCOPE_ALL and action == ACTION_RESET:
        text = (
            header
            + f"Это КРИТИЧНОЕ действие — сброс пароля и рассылка ВСЕМ ({len(targets)}) сразу.\n"
            + f"Для подтверждения введите слово: {CONFIRM_PHRASE}\n(или /cancel)"
        )
        await _reply(update, text)
        return AWAITING_CONFIRM_PHRASE

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Разослать", callback_data="confirm:yes")],
        [InlineKeyboardButton("Отмена", callback_data="cancel")],
    ])
    await _reply(update, header + "Продолжить?", reply_markup=keyboard)
    return CONFIRMING


@restricted
async def confirm_button(update, context):
    await update.callback_query.answer()
    from handlers.execute import run_broadcast
    return await run_broadcast(update, context)


@restricted
async def confirm_phrase(update, context):
    text = (update.message.text or "").strip()
    if text != CONFIRM_PHRASE:
        await update.message.reply_text(f"Не совпало. Введите точно «{CONFIRM_PHRASE}» (или /cancel):")
        return AWAITING_CONFIRM_PHRASE
    from handlers.execute import run_broadcast
    return await run_broadcast(update, context)
