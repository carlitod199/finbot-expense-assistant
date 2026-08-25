# -*- coding: utf-8 -*-
"""Report calculations and formatting (summary, week, budgets, confirmation)."""

from __future__ import annotations

import calendar
import os

from config.budgets import CATEGORIES
from finbot import dates, db

# Symbol prefixed to every amount the bot prints. Purely cosmetic: the app
# stores plain numbers and performs no currency conversion.
CURRENCY = os.environ.get("FINBOT_CURRENCY", "$")


def money(amount: float) -> str:
    """Format an amount as e.g. "$ 1,234.56"."""
    return f"{CURRENCY} {amount:,.2f}"


def pct(used: float, budget: float) -> str:
    """Percentage of the budget used, or an em dash when there is no budget."""
    if budget <= 0:
        return "—"
    return f"{(used / budget) * 100:.0f}%"


def _bar(used: float, budget: float, size: int = 10) -> str:
    """Small text progress bar for the category summary."""
    if budget <= 0:
        return ""
    fraction = min(used / budget, 1.0)
    filled = round(fraction * size)
    return "▰" * filled + "▱" * (size - filled)


# ---------------------------------------------------------------------------
# Expense confirmation
# ---------------------------------------------------------------------------

def expense_confirmation(category: str, amount: float, day, month: str) -> str:
    """Message sent right after an expense is stored."""
    spent = db.category_spend_for_month(category, month)
    logged = f"✅ Logged: {money(amount)} in *{category}* ({day.strftime('%Y-%m-%d')})."

    if not db.month_configured(month):
        return (
            f"{logged}\n\n"
            f"📌 {category} in {_month_label(month)}: {money(spent)} spent.\n"
            f"_No budget configured for {_month_label(month)} - add it in `config/budgets.py`._"
        )

    budget = db.budgets_for_month(month).get(category, 0.0)
    left = budget - spent
    lines = [
        logged,
        "",
        f"📌 {category} in {_month_label(month)}:",
        f"   Spent: {money(spent)} of {money(budget)} ({pct(spent, budget)})",
    ]
    if left >= 0:
        lines.append(f"   Left: {money(left)}")
    else:
        lines.append(f"   ⚠️ *OVER BUDGET* by {money(-left)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /summary
# ---------------------------------------------------------------------------

def month_summary(month: str) -> str:
    """Per-category spending vs budget for the given month."""
    if not db.month_configured(month):
        return _no_plan(month)
    budgets = db.budgets_for_month(month)
    spending = db.spend_by_category_for_month(month)

    lines = [f"📊 *Summary for {_month_label(month)}*", ""]
    total_spent = 0.0
    total_budget = 0.0
    for cat in CATEGORIES:
        budget = budgets.get(cat, 0.0)
        spent = spending.get(cat, 0.0)
        total_spent += spent
        total_budget += budget
        mark = "⚠️" if spent > budget and budget > 0 else "•"
        lines.append(f"{mark} {cat}")
        lines.append(
            f"    {money(spent)} / {money(budget)}  ({pct(spent, budget)})  {_bar(spent, budget)}"
        )

    lines.append("")
    total_mark = "⚠️" if total_spent > total_budget and total_budget > 0 else "▶️"
    lines.append(
        f"{total_mark} *Total: {money(total_spent)} / {money(total_budget)} "
        f"({pct(total_spent, total_budget)})*"
    )
    if total_spent > total_budget and total_budget > 0:
        lines.append(f"⚠️ *OVER BUDGET* by {money(total_spent - total_budget)}")
    else:
        lines.append(f"Left in total: {money(total_budget - total_spent)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /week
# ---------------------------------------------------------------------------

def week_summary() -> str:
    """This week's spending plus a straight-line projection for the month."""
    today = dates.today()
    month = dates.current_month()
    monday, sunday = dates.current_week(today)

    week_spent = db.total_spend_in_range(monday, sunday)
    month_spent = db.total_spend_for_month(month)
    month_budget = sum(db.budgets_for_month(month).values())

    elapsed_days = today.day
    days_in_month = dates.days_in_month(today)
    daily_rate = month_spent / elapsed_days if elapsed_days else 0.0
    projection = daily_rate * days_in_month

    lines = [
        f"🗓️ *Week {monday.strftime('%d %b')} – {sunday.strftime('%d %b')}*",
        f"Spent this week (7 categories): {money(week_spent)}",
        "",
        f"📈 *Month projection ({_month_label(month)})*",
        f"Spent so far: {money(month_spent)} over {elapsed_days} of {days_in_month} days",
        f"Rate: {money(daily_rate)}/day",
        f"Projected month-end: {money(projection)}",
        f"Total cap for the month: {money(month_budget)}",
        "",
    ]
    if month_budget <= 0:
        lines.append("No cap configured for this month.")
    elif projection > month_budget:
        lines.append(
            f"🔴 At the current rate the month ends *{money(projection - month_budget)} OVER* "
            "the cap. I recommend slowing down variable spending in the next few days."
        )
    else:
        lines.append(
            f"🟢 At the current rate the month ends *within the cap*, with "
            f"{money(month_budget - projection)} to spare. Keep the discipline."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /budgets
# ---------------------------------------------------------------------------

def budget_table(month: str) -> str:
    """Table of this month's budget per category."""
    if not db.month_configured(month):
        return _no_plan(month)
    budgets = db.budgets_for_month(month)
    lines = [f"🎯 *Budgets for {_month_label(month)}*", ""]
    total = 0.0
    for cat in CATEGORIES:
        budget = budgets.get(cat, 0.0)
        total += budget
        lines.append(f"• {cat}: {money(budget)}")
    lines.append("")
    lines.append(f"*Total variable spending: {money(total)}*")
    lines.append("")
    lines.append(
        "_Outside this cap: savings, one-off goals and fixed costs - "
        "see `config/budgets.py`._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context handed to the LLM for a purchase query
# ---------------------------------------------------------------------------

def budget_context(month: str) -> str:
    """Plain-text budget snapshot injected into the purchase-advice prompt."""
    budgets = db.budgets_for_month(month)
    spending = db.spend_by_category_for_month(month)
    lines = [
        f"Current month: {_month_label(month)}.",
        f"Currency symbol to use in the answer: {CURRENCY}",
    ]
    total_spent = total_budget = 0.0
    for cat in CATEGORIES:
        budget = budgets.get(cat, 0.0)
        spent = spending.get(cat, 0.0)
        total_spent += spent
        total_budget += budget
        lines.append(
            f"- {cat}: spent {money(spent)} / budget {money(budget)} "
            f"(left {money(budget - spent)})."
        )
    lines.append(
        f"Variable total: spent {money(total_spent)} / cap {money(total_budget)} "
        f"(left {money(total_budget - total_spent)})."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_label(month: str) -> str:
    """Turn "2026-08" into "August 2026"."""
    try:
        year, mm = month.split("-")
        return f"{calendar.month_name[int(mm)]} {year}"
    except (ValueError, IndexError, KeyError):
        return month


def _no_plan(month: str) -> str:
    """Message shown when the month has no budget configured."""
    spent = db.total_spend_for_month(month)
    return (
        f"ℹ️ There is no budget plan for *{_month_label(month)}* yet.\n\n"
        f"I keep logging expenses as usual (month total: {money(spent)}), but I "
        f"cannot compare them against a budget.\n\n"
        f"To configure a month, edit `config/budgets.py` and restart the bot."
    )
