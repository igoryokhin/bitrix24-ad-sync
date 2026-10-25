import logging

from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters,
)

import config
from state import (
    CHOOSING_SCOPE, CHOOSING_OU, AWAITING_NAME, CHOOSING_SEARCH_RESULT,
    CHOOSING_TEMPLATE, CHOOSING_ACTION, CONFIRMING, AWAITING_CONFIRM_PHRASE,
)
from handlers import menu, ou_picker, name_search, template_choice, action_choice, confirm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("tgbot")


def build_application():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")
    if not config.TELEGRAM_ADMIN_IDS:
        logger.warning("TELEGRAM_ADMIN_IDS пуст — ни один пользователь не сможет пользоваться ботом")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", menu.start),
            CommandHandler("broadcast", menu.start),
        ],
        states={
            CHOOSING_SCOPE: [CallbackQueryHandler(menu.choose_scope, pattern="^scope:")],
            CHOOSING_OU: [
                CallbackQueryHandler(ou_picker.paginate, pattern="^oupage:"),
                CallbackQueryHandler(ou_picker.choose_ou, pattern="^ou:"),
            ],
            AWAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_search.search_name)],
            CHOOSING_SEARCH_RESULT: [CallbackQueryHandler(name_search.choose_search_result, pattern="^pick:")],
            CHOOSING_TEMPLATE: [CallbackQueryHandler(template_choice.choose_template, pattern="^tmpl:")],
            CHOOSING_ACTION: [CallbackQueryHandler(action_choice.choose_action, pattern="^action:")],
            CONFIRMING: [CallbackQueryHandler(confirm.confirm_button, pattern="^confirm:yes$")],
            AWAITING_CONFIRM_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm.confirm_phrase)],
        },
        fallbacks=[
            CommandHandler("cancel", menu.cancel),
            CallbackQueryHandler(menu.cancel, pattern="^cancel$"),
        ],
    )
    app.add_handler(conv)
    return app


def main():
    app = build_application()
    logger.info("Бот запущен, polling…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
