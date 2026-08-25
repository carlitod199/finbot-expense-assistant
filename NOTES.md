# NOTES — factual inventory of the codebase

Working notes describing exactly what the code in this repository does.
No roadmap, no aspirational features. Everything below was read off the source.

---

## 1. What the project is

A Telegram bot that logs personal expenses written in plain language. Incoming
messages are sent to the Google Gemini API, which returns a strict JSON object
containing an intent, an amount, a category and a date. Expenses are stored in
SQLite and every confirmation compares the category total for the month against
a per-category monthly budget. The bot can also review a prospective purchase
and answer in a fixed advisor format.

It runs as a single long-lived Python process using Telegram **long polling**.
There is no web server, no webhook and no HTTP port.

---

## 2. Module inventory

```
finbot-expense-assistant/
├── config/
│   ├── __init__.py        # empty, marks the package
│   └── budgets.py         # the spending plan (edit this file)
├── finbot/
│   ├── __init__.py        # empty, marks the package
│   ├── main.py            # entry point, handler registration, polling loop
│   ├── db.py              # SQLite schema, seeding, reads and writes
│   ├── ai_client.py       # Google Gemini calls
│   ├── persona.py         # system prompts (advisor persona + extractor)
│   ├── handlers.py        # Telegram commands and free-text flow
│   ├── reports.py         # calculations and message formatting
│   └── dates.py           # timezone-anchored date helpers
├── .env.example
├── .gitignore
├── LICENSE
├── NOTES.md
└── requirements.txt
```

### `config/budgets.py`
Pure data, no logic.
- `CATEGORIES` — the 7 variable-spending categories, as an ordered list. The
  order defines the numbering the bot shows when it asks the user to pick one:
  `Groceries`, `Transport`, `Leisure`, `Delivery/Dining`, `Pharmacy`,
  `Shopping/Gifts`, `Unexpected`.
- `MONTHLY_BUDGETS` — `{"YYYY-MM": {category: amount}}`. Ships with three demo
  months (2026-08, 2026-09, 2026-10) filled with round fictional numbers.
- `OTHER_PLAN_LINES` — a descriptive dict of plan lines that sit *outside* the
  variable-spending cap (savings, a one-off goal, fixed costs). **Nothing in the
  code reads this dict.** It exists as documentation of the intent behind the
  `OUTSIDE_CATEGORIES` branch of the prompt.

### `finbot/dates.py`
All dates are anchored to one timezone read from `FINBOT_TZ` (default `UTC`).
If `zoneinfo` or the tz database is unavailable, `TZ` falls back to `None` and
the process-local time is used instead.
- `today()`, `current_month()` → `"YYYY-MM"`, `month_of(date)`,
  `days_in_month(date=None)`, `current_week(date=None)` → `(Monday, Sunday)`,
  `parse_iso(text)` → `date | None`.

### `finbot/db.py`
Holds one module-level `sqlite3.Connection` created on first use
(`check_same_thread=False`, `row_factory=sqlite3.Row`, `journal_mode=WAL`).
- `connect()`, `init_db()` — creates both tables and seeds budgets.
- Writes: `record_transaction(day, category, amount, description) -> int`.
- Reads: `month_configured(month)`, `budgets_for_month(month)`,
  `category_spend_for_month(category, month)`,
  `spend_by_category_for_month(month)`, `total_spend_for_month(month)`,
  `total_spend_in_range(start, end)`.

`total_spend_for_month` and `total_spend_in_range` deliberately filter
`category IN (the 7 categories)`, so any row stored under a different label
would not count toward the cap.

### `finbot/persona.py`
Three prompt constants/functions, all plain strings:
- `PERSONA` — the advisor character (rigorous, rational, never
  passive-aggressive, answers in English with concrete numbers).
- `PURCHASE_REPLY_FORMAT` — the fixed 5-line answer template for purchase advice.
- `extraction_prompt(today_iso)` — the extractor system prompt; it interpolates
  today's date and the 7 category names from `config/budgets.py`.

### `finbot/ai_client.py`
- `MODEL` — read from `GEMINI_MODEL` at import time, default `gemini-2.0-flash`.
- `client()` — lazily builds `genai.Client(api_key=os.environ["GEMINI_API_KEY"])`.
- `_response_text(resp)` — reads `resp.text`, falling back to concatenating
  `resp.candidates[0].content.parts`; returns `""` if both fail.
- `_extract_json(text)` — `json.loads`, falling back to the first `{...}` block
  found by regex; raises `ValueError` if there is none.
- `interpret_message(text)` — the extraction call.
- `answer_purchase_query(user_text, budget_context)` — the advice call.

### `finbot/reports.py`
Pure formatting and arithmetic; the only side effects are the `db` reads.
- `CURRENCY` — read from `FINBOT_CURRENCY` at import time, default `$`.
- `money(amount)` → `"$ 1,234.56"`; `pct(used, budget)` → `"132%"` or `"—"`
  when the budget is 0; `_bar()` → a 10-cell `▰▱` progress bar.
- `expense_confirmation()`, `month_summary()`, `week_summary()`,
  `budget_table()`, `budget_context()`, `_month_label("2026-08")` →
  `"August 2026"`, `_no_plan(month)`.

### `finbot/handlers.py`
- `_pending: dict[int, dict]` — **in-memory only**, keyed by `chat_id`, holding
  one expense awaiting a category answer. Lost on restart.
- `CONFIDENCE_THRESHOLD = 0.6`.
- Command handlers `cmd_start`, `cmd_help`, `cmd_summary`, `cmd_week`,
  `cmd_budgets`; free-text handler `msg_text`.
- Helpers `_handle_purchase_query`, `_handle_expense`, `_resolve_pending`,
  `_record_and_confirm`, `_category_menu`, `_match_category`.

### `finbot/main.py`
Loads `.env` (via `python-dotenv`, silently skipped if not installed) **before**
importing the `finbot` modules, because several of them read their configuration
at import time. Exits with an error if `TELEGRAM_BOT_TOKEN` or `GEMINI_API_KEY`
is missing, calls `db.init_db()`, registers the handlers and calls
`app.run_polling(allowed_updates=["message"])`.

---

## 3. Bot commands and their exact output

Registered commands: `/start`, `/help`, `/summary`, `/week`, `/budgets`.
Every reply is sent with `parse_mode=MARKDOWN`.

### `/start`
A fixed two-paragraph greeting explaining that expenses can be sent in plain
language and pointing at `/help`.

### `/help`
A fixed message listing three example expense phrasings, one purchase-review
phrasing, and the four commands with a one-line description each.

### `/summary` → `reports.month_summary(current_month)`
If the month has no budget rows, returns the `_no_plan` message instead. Otherwise:

```
📊 *Summary for August 2026*

⚠️ Groceries
    $ 1,320.50 / $ 1,000.00  (132%)  ▰▰▰▰▰▰▰▰▰▰
• Transport
    $ 35.00 / $ 400.00  (9%)  ▰▱▱▱▱▱▱▱▱▱
...
▶️ *Total: $ 1,355.50 / $ 2,300.00 (59%)*
Left in total: $ 944.50
```

The per-category marker is `⚠️` when spent > budget (and budget > 0), otherwise
`•`. The total line uses `⚠️` / `▶️` the same way, and the last line is either
`⚠️ *OVER BUDGET* by <amount>` or `Left in total: <amount>`.

### `/week` → `reports.week_summary()`

```
🗓️ *Week 24 Aug – 30 Aug*
Spent this week (7 categories): $ 1,355.50

📈 *Month projection (August 2026)*
Spent so far: $ 1,355.50 over 25 of 31 days
Rate: $ 54.22/day
Projected month-end: $ 1,680.82
Total cap for the month: $ 2,300.00

🟢 At the current rate the month ends *within the cap*, with $ 619.18 to spare. Keep the discipline.
```

The projection is a straight line: `month_spent / today.day * days_in_month`.
The closing line is one of three: "No cap configured for this month.", the
🔴 over-the-cap warning, or the 🟢 within-the-cap line.

### `/budgets` → `reports.budget_table(current_month)`

```
🎯 *Budgets for August 2026*

• Groceries: $ 1,000.00
...
*Total variable spending: $ 2,300.00*

_Outside this cap: savings, one-off goals and fixed costs - see `config/budgets.py`._
```

Falls back to `_no_plan` when the month is not configured.

### Expense confirmation (not a command)

```
✅ Logged: $ 1,200.00 in *Groceries* (2026-08-25).

📌 Groceries in August 2026:
   Spent: $ 1,320.50 of $ 1,000.00 (132%)
   ⚠️ *OVER BUDGET* by $ 320.50
```

The last line is `   Left: <amount>` when the category is still within budget.
When the month has no budget rows, the message instead reports the category
total and says no budget is configured.

### `_no_plan` message

```
ℹ️ There is no budget plan for *January 2030* yet.

I keep logging expenses as usual (month total: $ 0.00), but I cannot compare
them against a budget.

To configure a month, edit `config/budgets.py` and restart the bot.
```

### Category question (not a command)
When the category cannot be determined, the bot stores the expense in memory and
replies with an optional one-line reason, the question
`Which category should I log the $ 45.00 under? Reply with the number:`, the
numbered list of the 7 categories, and `Or type *cancel*.`

---

## 4. Database schema

SQLite, file path from `FINBOT_DB` (default `./finbot.db`), WAL journal mode.
Created by `init_db()` with `CREATE TABLE IF NOT EXISTS`.

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
    description TEXT,                -- the raw user message
    created_at  TEXT NOT NULL        -- local ISO timestamp, seconds precision
);

CREATE INDEX idx_trans_date ON transactions(spent_on);
CREATE INDEX idx_trans_cat  ON transactions(category);
```

Seeding: on every start-up, `init_db()` walks `MONTHLY_BUDGETS` and issues
`INSERT OR IGNORE` per (month, category). Months already present are never
overwritten, so budgets edited directly in the database survive restarts. To
re-import a month, delete its rows from `budgets` first.

Note that `transactions` has **no user or chat column**. The schema assumes a
single user; two people talking to the same bot instance would share one ledger.

---

## 5. LLM integration

- SDK: `google-genai`, called synchronously via
  `client().models.generate_content(...)`.
- Model: `GEMINI_MODEL`, default `gemini-2.0-flash`. Read once at import time.
- API key: `GEMINI_API_KEY`, read from the environment inside `client()`.

### Extraction call (`interpret_message`)
- `system_instruction` = `persona.extraction_prompt(today_iso)`, which embeds
  today's date and the 7 category names.
- `contents` = the raw user message.
- `temperature=0`, `max_output_tokens=500`,
  `response_mime_type="application/json"`.
- The reply is parsed by `_extract_json`, then every expected key is filled in
  with `setdefault` so downstream code never sees a missing field.

Expected JSON shape:

```json
{
  "intent": "log_expense" | "purchase_query" | "other",
  "amount": number | null,
  "category": "<one of the 7>" | "OUTSIDE_CATEGORIES" | "AMBIGUOUS" | null,
  "date": "YYYY-MM-DD" | null,
  "item_description": string | null,
  "confidence": number
}
```

`item_description` is returned by the model but **the code never uses it** — the
`description` column stores the raw user message instead.

### Advice call (`answer_purchase_query`)
- `system_instruction` = `PERSONA` + `"\n\n"` + `PURCHASE_REPLY_FORMAT`.
- `contents` = the month's budget snapshot from `reports.budget_context(month)`
  followed by the user message.
- `temperature=0.3`, `max_output_tokens=800`. The model's text is forwarded to
  Telegram verbatim, with Markdown parse mode.

### How ambiguity is handled
`_handle_expense` asks the user rather than guessing whenever **any** of these
hold:
1. `category` is not one of the 7 (this covers `"AMBIGUOUS"`,
   `"OUTSIDE_CATEGORIES"`, `null` and any hallucinated label), or
2. `confidence < 0.6`.

The pending expense (amount, raw text, date) goes into `_pending[chat_id]` and
the bot sends the numbered category menu. `"OUTSIDE_CATEGORIES"` additionally
prepends a sentence explaining that it does not look like variable spending.

The next message from that chat goes through `_resolve_pending` first:
- `cancel` / `cancelled` / `canceled` / `never mind` / `forget it` → drop it and
  reply "Ok, the entry was cancelled."
- a digit 1..7, a category name, or a keyword (`uber`, `supermarket`,
  `drugstore`, …) → record the expense under that category.
- anything else → `_pending` is kept and the message falls through to the normal
  LLM flow, so the user can change the subject without losing the pending entry.

A missing or non-positive `amount` short-circuits earlier: the bot asks how much
it was and stores nothing.

---

## 6. Environment variables

| Variable | Required | Default | Read in | Purpose |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | `main.py` | Bot token from @BotFather. Missing → process exits. |
| `GEMINI_API_KEY` | yes | — | `main.py` (presence check), `ai_client.client()` | Google Gemini API key. Missing → process exits. |
| `GEMINI_MODEL` | no | `gemini-2.0-flash` | `ai_client.py` (import time) | Gemini model id. |
| `FINBOT_DB` | no | `./finbot.db` | `db.py` (import time) | SQLite file path. |
| `FINBOT_TZ` | no | `UTC` | `dates.py` (import time) | IANA timezone anchoring "today", the month and the week. |
| `FINBOT_CURRENCY` | no | `$` | `reports.py` (import time) | Symbol printed before every amount. Cosmetic only. |

No other environment variable is read anywhere in the tree.

---

## 7. Data flow: Telegram message → stored expense

1. `run_polling` receives a `message` update. Non-command text reaches
   `handlers.msg_text`.
2. Empty text is dropped.
3. If `_pending` holds an entry for this `chat_id`, `_resolve_pending` runs
   first and may consume the message (cancel, or a category choice → step 8).
4. `ai_client.interpret_message(text)` calls Gemini with the extraction prompt.
   Any exception is logged and answered with "I had trouble understanding that."
5. `intent == "purchase_query"` → `_handle_purchase_query` builds the budget
   snapshot, calls Gemini again and forwards the answer. Nothing is stored.
6. `intent == "other"` → a fixed hint message. Nothing is stored.
7. `intent == "log_expense"` → `_handle_expense`. No amount → ask for it and
   stop. Unusable category or `confidence < 0.6` → park in `_pending`, send the
   category menu and stop.
8. `_record_and_confirm` resolves the month with `dates.month_of(day)` and calls
   `db.record_transaction(day, category, amount, raw_message)`, which INSERTs
   one row and commits.
9. `reports.expense_confirmation(...)` re-reads the category total for that
   month, compares it with the budget and the reply is sent.

The date used is the model's `date` field parsed by `parse_iso`, falling back to
`dates.today()`. Because the month comes from the expense date, a back-dated
expense is booked against the budget of *its own* month.

---

## 8. Limitations, rough edges and things that are not implemented

**Single user by design.** No `chat_id` or user column in `transactions`. Anyone
who finds the bot and messages it writes into the same ledger. There is no
allow-list, no authentication and no per-user isolation.

**No delete, edit or undo.** Once an expense is written there is no bot command
to correct or remove it; you have to edit the SQLite file by hand. `/summary`,
`/week` and `/budgets` are the only read commands, and there is no command to
list individual transactions.

**Pending state is in-memory.** A restart while a category question is
outstanding silently drops that expense.

**One global SQLite connection**, created with `check_same_thread=False` and
shared across the async handlers. Writes are small and serialised by the GIL in
practice, but there is no locking, no connection pool and no retry on
`database is locked`.

**Blocking calls inside async handlers.** Both Gemini calls and every SQLite
query are synchronous and run on the event loop, so one slow API call stalls the
whole bot. Fine at personal volume, wrong for anything shared.

**No test suite.** There are no tests in the repository at all.

**No retry, rate limiting or cost control** around the Gemini calls. Every text
message costs at least one API call; a purchase query costs two.

**Parsing accuracy is the model's.** `temperature=0` and a JSON mime type help,
but a mis-extracted amount is stored without any sanity check beyond
`amount > 0`. There is no upper bound, no duplicate detection and no currency
detection — a "45" is 45 units of whatever `FINBOT_CURRENCY` says.

**Markdown injection.** Replies use `ParseMode.MARKDOWN` and interpolate both
the raw model output and user-derived text. Unbalanced `*` or `_` characters
make Telegram reject the message with a 400 rather than sending it.

**Currency is cosmetic.** Amounts are stored as bare `REAL`. `FINBOT_CURRENCY`
only changes the printed symbol; there is no conversion and no per-transaction
currency. Formatting is fixed to the `1,234.56` convention.

**Negative "left" amounts** are printed literally in `budget_context`
(e.g. `left $ -320.50`) rather than as an over-budget phrase. Only the
confirmation and summary messages use the `OVER BUDGET` wording.

**`OTHER_PLAN_LINES` is dead configuration** — declared in `config/budgets.py`
and never imported. The concept it documents only exists inside the prompt, as
the `OUTSIDE_CATEGORIES` sentinel.

**Budget months must be added by hand.** There is no rollover: once the calendar
passes the last month in `MONTHLY_BUDGETS`, every report falls back to the
"no budget plan" message until someone edits `config/budgets.py` and restarts.

**`_match_category` keywords are English-only** and matched by substring, so a
description containing an unrelated occurrence of a keyword can match. The
substring rule `name.split("/")[0] in t` also means a long sentence may
accidentally resolve to a category.

**Timezone fallback is silent.** If `zoneinfo` cannot resolve `FINBOT_TZ`, `TZ`
becomes `None` and the bot quietly uses the host's local time instead of
failing loudly.

**Deployment.** Polling only — no webhook support and no HTTP port, so on
platforms that expect a web service this must be deployed as a worker. If
`FINBOT_DB` is not pointed at persistent storage, the history is lost on every
redeploy.
