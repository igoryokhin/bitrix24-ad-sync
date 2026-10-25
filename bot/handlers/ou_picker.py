import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler

from auth import restricted
from state import CHOOSING_OU
import queries

PAGE_SIZE = 8


def _build_page(ous, page):
    start = page * PAGE_SIZE
    chunk = ous[start:start + PAGE_SIZE]
    buttons = [[InlineKeyboardButton(o["name"], callback_data=f"ou:{start + i}")] for i, o in enumerate(chunk)]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"oupage:{page - 1}"))
    if start + PAGE_SIZE < len(ous):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"oupage:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


@restricted
async def enter_department_picker(update, context):
    query = update.callback_query
    await query.edit_message_text("Загружаю список отделов…")
    try:
        ous = await asyncio.to_thread(queries.get_ous)
    except Exception as e:
        await query.edit_message_text(f"Не удалось получить список отделов: {e}")
        return ConversationHandler.END
    if not ous:
        await query.edit_message_text("Отделов не найдено.")
        return ConversationHandler.END
    context.user_data["ous"] = ous
    await query.edit_message_text("Выберите отдел:", reply_markup=_build_page(ous, 0))
    return CHOOSING_OU


@restricted
async def paginate(update, context):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":", 1)[1])
    ous = context.user_data.get("ous", [])
    await query.edit_message_text("Выберите отдел:", reply_markup=_build_page(ous, page))
    return CHOOSING_OU


@restricted
async def choose_ou(update, context):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    ous = context.user_data.get("ous", [])
    if idx >= len(ous):
        await query.edit_message_text("Устаревший выбор, начните заново: /start")
        return ConversationHandler.END

    ou = ous[idx]
    context.user_data["scope_label"] = f"отдел «{ou['name']}»"
    context.user_data["base_dn"] = ou["dn"]

    from handlers.template_choice import ask_template
    return await ask_template(update, context)
