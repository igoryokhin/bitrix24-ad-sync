from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from auth import restricted
from state import CHOOSING_SCOPE

SCOPE_ALL = "all"
SCOPE_DEPARTMENT = "dept"
SCOPE_NOT_RECEIVED = "not_received"
SCOPE_BY_NAME = "by_name"

SCOPE_LABELS = {
    SCOPE_ALL: "Всем активным",
    SCOPE_DEPARTMENT: "По отделу",
    SCOPE_NOT_RECEIVED: "Кто ещё не получил",
    SCOPE_BY_NAME: "По ФИО",
}


def _scope_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(SCOPE_LABELS[SCOPE_ALL], callback_data=f"scope:{SCOPE_ALL}")],
        [InlineKeyboardButton(SCOPE_LABELS[SCOPE_DEPARTMENT], callback_data=f"scope:{SCOPE_DEPARTMENT}")],
        [InlineKeyboardButton(SCOPE_LABELS[SCOPE_NOT_RECEIVED], callback_data=f"scope:{SCOPE_NOT_RECEIVED}")],
        [InlineKeyboardButton(SCOPE_LABELS[SCOPE_BY_NAME], callback_data=f"scope:{SCOPE_BY_NAME}")],
    ])


async def _show_scope_menu(update, context, prefix=""):
    context.user_data.clear()
    text = prefix + "Кому отправить?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_scope_keyboard())
    else:
        await update.effective_message.reply_text(text, reply_markup=_scope_keyboard())
    return CHOOSING_SCOPE


async def send_scope_menu(message, context, prefix=""):
    """Как _show_scope_menu, но всегда отдельным новым сообщением (не
    редактирует старое) — используется после завершения рассылки."""
    context.user_data.clear()
    await message.reply_text(prefix + "Кому отправить?", reply_markup=_scope_keyboard())
    return CHOOSING_SCOPE


@restricted
async def start(update, context):
    return await _show_scope_menu(
        update, context,
        "Рассылка учётных данных (сброс пароля + сообщение в Bitrix24).\n",
    )


@restricted
async def choose_scope(update, context):
    query = update.callback_query
    await query.answer()
    scope = query.data.split(":", 1)[1]
    context.user_data["scope"] = scope

    if scope == SCOPE_DEPARTMENT:
        from handlers.ou_picker import enter_department_picker
        return await enter_department_picker(update, context)
    if scope == SCOPE_BY_NAME:
        from handlers.name_search import ask_name
        return await ask_name(update, context)

    context.user_data["scope_label"] = SCOPE_LABELS[scope]
    from handlers.template_choice import ask_template
    return await ask_template(update, context)


@restricted
async def cancel(update, context):
    if update.callback_query:
        await update.callback_query.answer()
    return await _show_scope_menu(update, context, "Отменено.\n\n")
