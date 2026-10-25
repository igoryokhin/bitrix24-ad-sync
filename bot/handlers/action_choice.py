from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from auth import restricted
from state import CHOOSING_ACTION
from handlers.menu import SCOPE_NOT_RECEIVED

ACTION_RESET = "reset"
ACTION_RESEND = "resend"

ACTION_LABELS = {
    ACTION_RESET: "Сбросить (новый пароль)",
    ACTION_RESEND: "Напомнить (текущий пароль)",
}

KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton(f"🔄 {ACTION_LABELS[ACTION_RESET]}", callback_data=f"action:{ACTION_RESET}")],
    [InlineKeyboardButton(f"📨 {ACTION_LABELS[ACTION_RESEND]}", callback_data=f"action:{ACTION_RESEND}")],
    [InlineKeyboardButton("Отмена", callback_data="cancel")],
])


async def ask_action(update, context):
    """Вызывается внутриигрово (не регистрируется как хендлер сама по
    себе) — может прийти и после callback-кнопки, и после текстового
    сообщения (быстрый путь поиска по ФИО с одним совпадением)."""
    if context.user_data.get("scope") == SCOPE_NOT_RECEIVED:
        # У этих людей ещё нет сохранённого пароля (они ничего не
        # получали) — напомнить нечего, только сброс имеет смысл.
        context.user_data["action"] = ACTION_RESET
        from handlers.confirm import show_confirm
        return await show_confirm(update, context)

    text = "Что сделать?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=KEYBOARD)
    else:
        await update.message.reply_text(text, reply_markup=KEYBOARD)
    return CHOOSING_ACTION


@restricted
async def choose_action(update, context):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    context.user_data["action"] = action

    from handlers.confirm import show_confirm
    return await show_confirm(update, context)
