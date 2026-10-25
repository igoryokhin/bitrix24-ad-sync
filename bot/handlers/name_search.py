import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler

from auth import restricted
from state import AWAITING_NAME, CHOOSING_SEARCH_RESULT
import queries


@restricted
async def ask_name(update, context):
    query = update.callback_query
    await query.edit_message_text("Введите часть ФИО для поиска:")
    return AWAITING_NAME


@restricted
async def search_name(update, context):
    text = (update.message.text or "").strip()
    if len(text) < 2:
        await update.message.reply_text("Слишком короткий запрос, введите ещё раз (или /cancel):")
        return AWAITING_NAME

    try:
        users = await asyncio.to_thread(queries.get_active_users, None, text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка поиска: {e}")
        return ConversationHandler.END

    if not users:
        await update.message.reply_text("Никого не найдено, попробуйте ещё раз (или /cancel):")
        return AWAITING_NAME

    if len(users) == 1:
        u = users[0]
        context.user_data["targets"] = [u["dn"]]
        context.user_data["scope_label"] = f"{u['display_name']} ({u['login']})"
        from handlers.template_choice import ask_template
        return await ask_template(update, context)

    context.user_data["search_results"] = users[:20]
    buttons = [
        [InlineKeyboardButton(f"{u['display_name']} ({u['login']})", callback_data=f"pick:{i}")]
        for i, u in enumerate(users[:20])
    ]
    buttons.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    await update.message.reply_text("Найдено несколько, выберите:", reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSING_SEARCH_RESULT


@restricted
async def choose_search_result(update, context):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    results = context.user_data.get("search_results", [])
    if idx >= len(results):
        await query.edit_message_text("Устаревший выбор, начните заново: /start")
        return ConversationHandler.END

    u = results[idx]
    context.user_data["targets"] = [u["dn"]]
    context.user_data["scope_label"] = f"{u['display_name']} ({u['login']})"
    from handlers.template_choice import ask_template
    return await ask_template(update, context)
