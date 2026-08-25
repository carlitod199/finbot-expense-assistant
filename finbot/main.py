# -*- coding: utf-8 -*-
"""Entry point: initialise the database and start the bot in polling mode."""

from __future__ import annotations

import logging
import os
import sys


def _load_env() -> None:
    """Load a .env file if python-dotenv is installed (optional)."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except ImportError:
        pass


# The .env file must be loaded BEFORE the finbot modules are imported: several
# of them read their configuration (FINBOT_DB, FINBOT_TZ, FINBOT_CURRENCY,
# GEMINI_MODEL) at import time.
_load_env()

from telegram.ext import (  # noqa: E402 - imported after _load_env() on purpose
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from finbot import db, handlers  # noqa: E402 - same reason

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("finbot")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("ERROR: set the TELEGRAM_BOT_TOKEN environment variable.")
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("ERROR: set the GEMINI_API_KEY environment variable.")

    db.init_db()
    log.info("Database initialised at %s", db.DB_PATH)

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("summary", handlers.cmd_summary))
    app.add_handler(CommandHandler("week", handlers.cmd_week))
    app.add_handler(CommandHandler("budgets", handlers.cmd_budgets))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.msg_text))

    log.info("Bot started (polling). Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
