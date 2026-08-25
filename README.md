# FinBot — Expense Assistant

A Telegram bot that logs expenses written in plain language, parses them with an LLM into structured records, and answers as a budget-aware financial advisor rather than a passive ledger.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57)
![License](https://img.shields.io/badge/License-MIT-blue)

---

## Overview

You send `spent 45 at the supermarket`. The bot extracts the amount, the category and the date, stores the expense, and replies with what you have now spent in that category this month against its budget — and tells you plainly when you have gone over.

You send `I want to buy headphones for 300`. It does not store anything. It reads your current month, and answers with the amount, the impact on the month, whether it breaks a budget, a priority score from 0 to 10, and a recommendation.

The interesting part of this project is not the Telegram plumbing. It is the boundary between a probabilistic parser and a ledger that has to be correct: **the bot asks instead of guessing.**

## Problem

Expense trackers fail for the same reason to-do apps fail — the friction of structured entry. An app that requires you to pick a category from a dropdown and type an amount into a form is an app you stop opening after nine days.

Removing that friction by letting people write in plain language moves the problem rather than solving it. Now something has to turn "grabbed lunch, 32" into a typed record, and that something is a language model, which is confidently wrong some of the time. A ledger that silently books a mis-parsed amount into a mis-chosen category is worse than no ledger, because you will trust it.

## Solution

The model's output is treated as a **proposal, not a result**. Every extraction comes back with an explicit confidence score and a category that must be one of a fixed set. The bot refuses the proposal and asks the user when any of these hold:

- the category is not one of the seven known categories, or
- the model returned one of two sentinel values — `AMBIGUOUS`, or `OUTSIDE_CATEGORIES` for something that is not variable spending at all, or
- confidence is below `0.6`.

The pending expense is parked and the bot sends a numbered menu. The next message is checked against that menu first, so answering `2` resolves it — but a message that is clearly a new subject falls through to the normal flow and the pending entry survives. A missing or non-positive amount short-circuits even earlier: the bot asks how much it was and stores nothing.

The result is a bot that is occasionally chatty and never quietly wrong.

## Key features

- **Natural-language expense logging** — `spent 45 at the supermarket`, `35 on the taxi`, `takeaway 60`.
- **Structured extraction** via Google Gemini with `temperature=0` and a JSON response type, into a fixed schema of intent, amount, category, date and confidence.
- **Ask-don't-guess** disambiguation with a numbered menu, keyword matching, and a cancel path.
- **Budget-aware confirmations** — every logged expense reports the category total for the month, the budget, the percentage, and how much is left or by how much it is over.
- **Purchase review** — a prospective purchase is answered in a fixed five-line advisor format including a priority score and a recommendation.
- **Reports** — `/summary` (month by category, with progress bars), `/week` (week total plus a straight-line month-end projection), `/budgets` (the configured plan).
- **Back-dating that respects the calendar** — an expense dated last month is booked against *last month's* budget, not this one.
- **Timezone-anchored dates**, configurable, so "today" and "this week" mean what the user means.

## Architecture

```
Telegram (long polling)
        │
        ▼
   handlers.py ──────────────► _pending[chat_id]   (in-memory disambiguation)
        │
        ├──► ai_client.py ──► Google Gemini
        │         ▲              extraction prompt (JSON, temperature 0)
        │         └── persona.py advisor prompt + reply format
        │
        ├──► db.py ─────────► SQLite (WAL)
        │
        └──► reports.py ────► formatting + arithmetic
                  │
                  └── dates.py  (timezone-anchored today / month / week)
```

Deliberately layered so that the parts that must be correct are the parts that are pure:

| Module | Responsibility | Purity |
|---|---|---|
| `dates.py` | Timezone-anchored date arithmetic | Pure |
| `reports.py` | Budget maths and message formatting | Pure except for reads |
| `db.py` | Schema, writes, aggregate reads | The only writer |
| `ai_client.py` | Gemini calls, JSON extraction and repair | The only network I/O |
| `persona.py` | The two system prompts | Pure data |
| `handlers.py` | Telegram commands and the free-text flow | Orchestration only |
| `config/budgets.py` | The spending plan | Pure data |

## Tech stack

**Language** Python 3.10+
**Bot** `python-telegram-bot` (long polling — no webhook, no HTTP port)
**LLM** Google Gemini via `google-genai`, default `gemini-2.0-flash`
**Storage** SQLite with WAL journalling
**Config** Environment variables via `python-dotenv`

## Project structure

```
├── config/
│   └── budgets.py         The spending plan — edit this file
├── finbot/
│   ├── main.py            Entry point, handler registration, polling loop
│   ├── handlers.py        Commands and the free-text flow
│   ├── ai_client.py       Gemini calls, JSON extraction with fallback
│   ├── persona.py         Advisor persona and extraction prompts
│   ├── db.py              SQLite schema, seeding, reads and writes
│   ├── reports.py         Budget arithmetic and message formatting
│   └── dates.py           Timezone-anchored date helpers
├── .env.example
└── requirements.txt
```

## Database

SQLite, two tables, created on first run.

```sql
CREATE TABLE budgets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    month    TEXT NOT NULL,          -- "YYYY-MM"
    category TEXT NOT NULL,
    amount   REAL NOT NULL,
    UNIQUE(month, category)
);

CREATE TABLE transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    spent_on    TEXT NOT NULL,       -- "YYYY-MM-DD"
    category    TEXT NOT NULL,
    amount      REAL NOT NULL,
    description TEXT,                -- the raw user message, kept verbatim
    created_at  TEXT NOT NULL
);
```

Budgets are seeded from `config/budgets.py` with `INSERT OR IGNORE`, so a month already present in the database is never overwritten by a restart. To re-import a month, delete its rows first.

The `description` column stores the **raw user message** rather than the model's paraphrase. If the extraction was wrong, the original sentence is still there to correct it against — the model's own `item_description` field is deliberately discarded.

## Commands

| Command | What it does |
|---|---|
| `/start` | Greeting and how to use it. |
| `/help` | Example phrasings and the command list. |
| `/summary` | This month by category: spent, budget, percentage, progress bar, and the total with an over-budget warning. |
| `/week` | This week's total (Monday–Sunday) plus a straight-line projection of where the month ends at the current rate. |
| `/budgets` | The configured budget table for the current month. |

Anything that is not a command is treated as free text and routed by the model's `intent`: log an expense, review a purchase, or a hint message.

## Configuration

Budgets live in `config/budgets.py` as plain data:

```python
MONTHLY_BUDGETS = {
    "2026-08": {
        "Groceries": 1000.0,
        "Transport": 400.0,
        ...
    },
}
```

The seven categories — Groceries, Transport, Leisure, Delivery/Dining, Pharmacy, Shopping/Gifts, Unexpected — are the variable-spending cap. The list order defines the numbering in the disambiguation menu, and the aggregate queries filter on exactly these seven, so a row stored under any other label does not count against the cap.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | Bot token from @BotFather. Missing values exit at start-up. |
| `GEMINI_API_KEY` | yes | — | Google Gemini API key. |
| `GEMINI_MODEL` | no | `gemini-2.0-flash` | Model id. |
| `FINBOT_DB` | no | `./finbot.db` | SQLite file path. Point this at persistent storage on an ephemeral host. |
| `FINBOT_TZ` | no | `UTC` | IANA timezone anchoring "today", the month and the week. |
| `FINBOT_CURRENCY` | no | `$` | Symbol printed before every amount. Cosmetic — there is no conversion. |

`.env.example` contains placeholders only.

## Installation

```bash
git clone https://github.com/carlitod199/finbot-expense-assistant.git
cd finbot-expense-assistant

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in the two required values
```

Create the bot with [@BotFather](https://t.me/BotFather) (`/newbot`) for the Telegram token, and get a Gemini key from [Google AI Studio](https://aistudio.google.com/apikey).

## Running locally

```bash
python -m finbot.main
```

The process polls Telegram; there is no port to expose. On first run it creates the database and seeds the configured budgets. Edit `config/budgets.py` and restart to add a month.

## Technical decisions

**The model proposes, the code disposes.** Every extraction is validated against a closed set of categories and a confidence floor before anything is written. Two sentinel values — `AMBIGUOUS` and `OUTSIDE_CATEGORIES` — give the model an explicit way to decline rather than forcing it to pick the least-wrong option, which is where LLM extraction usually goes wrong.

**The raw message is the source of truth.** The database stores what the user typed, not what the model understood. This costs a text column and buys the ability to audit or reprocess every record.

**Pure core, impure edges.** Date arithmetic and budget maths have no I/O and no model in them, so they are the parts that are trivially verifiable. All network calls live in one module, all writes in another.

**The month comes from the expense date, not from today.** A back-dated expense is booked against its own month's budget. This is the behaviour people expect and the one that is easy to get wrong.

**JSON extraction with a fallback.** The response is requested as `application/json`, parsed with `json.loads`, and — when a model wraps its output in prose or a code fence anyway — recovered with a regex over the first `{...}` block. Missing keys are filled with `setdefault`, so downstream code never sees a partial object.

**Long polling, not webhooks.** No public URL, no TLS certificate, no inbound port. For a single-user bot that is the correct trade: it runs anywhere a Python process runs.

## Challenges

**Deciding when to interrupt.** A bot that asks about everything is worse than a dropdown; a bot that never asks is a corrupt ledger. The threshold ended up being three independent conditions rather than one confidence number, because the failure modes are different: an unknown category is a schema violation, `OUTSIDE_CATEGORIES` is a correct answer to the wrong question, and low confidence is genuine uncertainty. Each gets a different message.

**Keeping pending state without losing the conversation.** When a category question is outstanding, the next message might be the answer — or might be a completely new expense. Consuming it unconditionally would swallow real input. The resolver only claims the message if it matches a cancel word, a menu number, a category name or a known keyword; otherwise the pending entry stays parked and the message flows on normally.

**Straight-line projection is a lie you have to label.** `/week` projects the month-end total from the current daily rate. That is naive — spending is not uniform — so the message says what it is doing and prints the rate it used, rather than presenting a number as a forecast.

## Limitations

This is a single-user personal tool. Stated plainly:

- **No authentication and no per-user isolation.** `transactions` has no chat or user column. Anyone who finds a running instance writes into the same ledger and spends its API quota. Fixing this means a user column and an allow-list, and is the first thing to do before sharing an instance.
- **No delete, edit or undo**, and no command to list individual transactions. Corrections mean editing the SQLite file.
- **Pending disambiguation state is in memory** and is lost on restart.
- **Blocking I/O on the event loop.** Both the Gemini calls and every SQLite query are synchronous. Fine at personal volume, wrong for anything shared.
- **One global SQLite connection** shared across async handlers, with no locking and no retry on `database is locked`.
- **No test suite.**
- **No retry, rate limiting or cost control** on the LLM calls. Every text message costs at least one call; a purchase query costs two.
- **Amounts are trusted beyond `amount > 0`** — no upper bound, no duplicate detection, no currency detection.
- **Budget months must be added by hand.** There is no rollover; past the last configured month, every report falls back to "no budget plan".
- **Markdown replies can be rejected.** Telegram Markdown parse mode plus interpolated model output means unbalanced `*` or `_` can produce a 400 instead of a message.
- Keyword matching in the disambiguation menu is English-only and substring-based, so a long sentence can resolve to the wrong category.

## License

MIT — see [LICENSE](LICENSE).
