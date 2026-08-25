# -*- coding: utf-8 -*-
"""Telegram handlers: slash commands and free-form text messages."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config.budgets import CATEGORIES
from finbot import ai_client, dates, db, reports

log = logging.getLogger(__name__)

# Lightweight in-memory state: expenses waiting for the user to pick a category.
# key = chat_id -> {"amount": float, "description": str, "day": date}
_pending: dict[int, dict] = {}

CONFIDENCE_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 I am your financial advisor. Send me your expenses in plain "
        "language - e.g. *spent 45 at the supermarket*, *35 on a cab*, "
        "*delivery 60*.\n\n"
        "I log them, show how much is left in the category and warn you when "
        "you go over budget. Use /help to see every command.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *How to use me*\n\n"
        "Just send an expense, e.g.:\n"
        "• `spent 45 at the supermarket`\n"
        "• `35 on a cab`\n"
        "• `delivery 60`\n\n"
        "Want a purchase reviewed? Say:\n"
        "• `I want to buy headphones for 300`\n"
        "I answer with the amount, the impact on the month, whether it breaks a "
        "budget, a priority score (0-10) and a recommendation.\n\n"
        "*Commands:*\n"
        "/summary — this month's spending per category vs budget (% used)\n"
        "/week — this week's spending (Mon-Sun) and the month-end projection\n"
        "/budgets — this month's budget table\n"
        "/help — this message"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        reports.month_summary(dates.current_month()), parse_mode=ParseMode.MARKDOWN
    )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        reports.week_summary(), parse_mode=ParseMode.MARKDOWN
    )


async def cmd_budgets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        reports.budget_table(dates.current_month()), parse_mode=ParseMode.MARKDOWN
    )


# ---------------------------------------------------------------------------
# Free-form text messages
# ---------------------------------------------------------------------------

async def msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    # 1) Is there an expense waiting for a category? Try to resolve it first.
    if chat_id in _pending:
        if await _resolve_pending(update, chat_id, text):
            return
        # Not a category answer: fall through to the normal flow
        # (the user changed the subject).

    # 2) Interpret the message with the LLM (Gemini).
    try:
        data = ai_client.interpret_message(text)
    except Exception:  # noqa: BLE001
        log.exception("Failed to interpret message")
        await update.message.reply_text(
            "I had trouble understanding that. Could you send it again?"
        )
        return

    intent = data.get("intent")

    if intent == "purchase_query":
        await _handle_purchase_query(update, text)
    elif intent == "log_expense":
        await _handle_expense(update, chat_id, data, text)
    else:
        await update.message.reply_text(
            "I did not spot an expense there. To log one, try something like "
            "*spent 45 at the supermarket*. To review a purchase, "
            "*I want to buy X for Y*. See /help.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _handle_purchase_query(update: Update, text: str) -> None:
    """Answer a "should I buy this?" message using the advisor persona."""
    month = dates.current_month()
    context_text = reports.budget_context(month)
    try:
        answer = ai_client.answer_purchase_query(text, context_text)
    except Exception:  # noqa: BLE001
        log.exception("Purchase query failed")
        await update.message.reply_text(
            "I could not review that right now. Please try again in a moment."
        )
        return
    await update.message.reply_text(answer, parse_mode=ParseMode.MARKDOWN)


async def _handle_expense(update: Update, chat_id: int, data: dict, text: str) -> None:
    """Store an extracted expense, or ask for the category when unsure."""
    amount = data.get("amount")
    category = data.get("category")
    confidence = float(data.get("confidence") or 0.0)
    day = dates.parse_iso(data.get("date") or "") or dates.today()

    if not amount or amount <= 0:
        await update.message.reply_text(
            "I understood that as an expense, but I did not catch the amount. "
            "How much was it? (e.g. *45* or *45 at the supermarket*)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Category outside the 7, ambiguous, or low confidence -> ask the user.
    if category not in CATEGORIES or confidence < CONFIDENCE_THRESHOLD:
        _pending[chat_id] = {"amount": float(amount), "description": text, "day": day}
        reason = ""
        if category == "OUTSIDE_CATEGORIES":
            reason = (
                "That does not seem to fit the 7 variable spending categories "
                "(it may be a fixed cost, a savings transfer or a one-off goal).\n"
            )
        await update.message.reply_text(
            f"{reason}Which category should I log the {reports.money(float(amount))} under? "
            "Reply with the number:\n\n" + _category_menu() +
            "\n\nOr type *cancel*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _record_and_confirm(update, category, float(amount), day, text)


async def _resolve_pending(update: Update, chat_id: int, text: str) -> bool:
    """Try to read `text` as the category choice for the pending expense.
    Returns True if the message was consumed."""
    lowered = text.lower()
    if lowered in {"cancel", "cancelled", "canceled", "never mind", "forget it"}:
        _pending.pop(chat_id, None)
        await update.message.reply_text("Ok, the entry was cancelled.")
        return True

    category = _match_category(text)
    if category is None:
        return False  # not a category choice; continue with the normal flow

    pending = _pending.pop(chat_id)
    await _record_and_confirm(
        update, category, pending["amount"], pending["day"], pending["description"]
    )
    return True


async def _record_and_confirm(
    update: Update, category: str, amount: float, day, description: str
) -> None:
    """Persist the expense and reply with the budget status of the category."""
    month = dates.month_of(day)
    db.record_transaction(day, category, amount, description)
    await update.message.reply_text(
        reports.expense_confirmation(category, amount, day, month),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------

def _category_menu() -> str:
    """Numbered list of the 7 categories, used in the clarifying question."""
    return "\n".join(f"{i}. {c}" for i, c in enumerate(CATEGORIES, start=1))


def _match_category(text: str) -> str | None:
    """Resolve free text ("3", "groceries", "uber") to one of the 7 categories."""
    t = text.strip().lower()
    # By number (1..7)
    if t.isdigit():
        idx = int(t)
        if 1 <= idx <= len(CATEGORIES):
            return CATEGORIES[idx - 1]
        return None
    # By name / keyword
    for cat in CATEGORIES:
        name = cat.lower()
        if t == name or t in name or name.split("/")[0] in t:
            return cat
    keywords = {
        "grocery": "Groceries", "groceries": "Groceries",
        "supermarket": "Groceries", "food": "Groceries",
        "transport": "Transport", "fuel": "Transport", "petrol": "Transport",
        "gas": "Transport", "cab": "Transport", "taxi": "Transport", "uber": "Transport",
        "leisure": "Leisure", "fun": "Leisure",
        "delivery": "Delivery/Dining", "dining": "Delivery/Dining",
        "restaurant": "Delivery/Dining", "takeaway": "Delivery/Dining",
        "pharmacy": "Pharmacy", "drugstore": "Pharmacy", "medicine": "Pharmacy",
        "shopping": "Shopping/Gifts", "gift": "Shopping/Gifts", "gifts": "Shopping/Gifts",
        "unexpected": "Unexpected", "emergency": "Unexpected",
    }
    for key, cat in keywords.items():
        if key in t:
            return cat
    return None
