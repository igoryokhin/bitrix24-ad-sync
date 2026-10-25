import functools
import logging

import config

logger = logging.getLogger("tgbot.auth")


def restricted(handler):
    """Применяется к каждому хендлеру (команды, текст, callback-кнопки) —
    update.effective_user одинаково доступен во всех этих случаях."""
    @functools.wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in config.TELEGRAM_ADMIN_IDS:
            uid = user.id if user else "unknown"
            logger.warning("Unauthorized access attempt by %s", uid)
            if update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text("⛔ Доступ запрещён.")
            return None
        return await handler(update, context, *args, **kwargs)
    return wrapper
