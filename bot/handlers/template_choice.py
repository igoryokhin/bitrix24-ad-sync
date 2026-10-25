from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from auth import restricted
from state import CHOOSING_TEMPLATE

KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("AD (логин/пароль домена)", callback_data="tmpl:ad")],
    [InlineKeyboardButton("Почта", callback_data="tmpl:mail")],
    [InlineKeyboardButton("Отмена", callback_data="cancel")],
])


async def ask_template(update, context):
    """Вызывается внутриигрово из других хендлеров (не регистрируется как
    хендлер сама по себе) — может прийти и после callback-кнопки, и после
    текстового сообщения (быстрый путь поиска по ФИО с одним совпадением)."""
    text = "Какой шаблон сообщения использовать?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=KEYBOARD)
    else:
        await update.message.reply_text(text, reply_markup=KEYBOARD)
    return CHOOSING_TEMPLATE


@restricted
async def choose_template(update, context):
    query = update.callback_query
    await query.answer()
    template = query.data.split(":", 1)[1]
    context.user_data["template"] = template

    from handlers.action_choice import ask_action
    return await ask_action(update, context)
