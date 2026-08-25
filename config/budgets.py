# -*- coding: utf-8 -*-
"""Central configuration for the spending plan.

>>> EDIT THIS FILE when the plan changes (e.g. to add a new month). <<<

On start-up the bot seeds the `budgets` table in SQLite from the values below.
Months that already exist in the database are NOT overwritten (INSERT OR
IGNORE), so you can tweak a month's budget directly in the database without
losing the edit. To force a month to be re-imported, delete that month's rows
from the `budgets` table.

The figures below are fictional demo values, not anyone's real budget.
"""

# The 7 variable-spending categories.
# The order defines the numbering used when the bot asks the user to pick one.
CATEGORIES = [
    "Groceries",
    "Transport",
    "Leisure",
    "Delivery/Dining",
    "Pharmacy",
    "Shopping/Gifts",
    "Unexpected",
]

# Monthly budget per category. Month key uses the "YYYY-MM" format.
# Amounts are plain numbers; the display currency is set by FINBOT_CURRENCY.
MONTHLY_BUDGETS = {
    "2026-08": {
        "Groceries": 1000,
        "Transport": 400,
        "Leisure": 200,
        "Delivery/Dining": 200,
        "Pharmacy": 100,
        "Shopping/Gifts": 300,
        "Unexpected": 100,
    },
    "2026-09": {
        "Groceries": 1000,
        "Transport": 400,
        "Leisure": 200,
        "Delivery/Dining": 200,
        "Pharmacy": 100,
        "Shopping/Gifts": 300,
        "Unexpected": 100,
    },
    "2026-10": {
        "Groceries": 1200,
        "Transport": 500,
        "Leisure": 300,
        "Delivery/Dining": 300,
        "Pharmacy": 100,
        "Shopping/Gifts": 400,
        "Unexpected": 200,
    },
}

# Other lines of the plan. These are deliberately kept OUT of the variable
# spending cap. The bot only needs to "know they exist" so it can guide the
# user and so that expenses which fall outside the 7 categories trigger a
# clarifying question instead of being filed under the wrong bucket.
#
# Demo values only - replace them with your own.
OTHER_PLAN_LINES = {
    "Emergency fund": {
        "type": "savings",
        "monthly_amount": 500.00,
        "note": "Fixed monthly savings target. Not an expense.",
    },
    "Travel fund": {
        "type": "one_off_goal",
        "cap": 3000.00,
        "target_month": "2026-12",
        "note": "Has its own bucket, outside the variable spending cap.",
    },
    "Fixed costs": {
        "type": "recurring",
        "items": {
            "Rent": "Paid on the 5th of each month.",
            "Utilities": "Electricity, water and internet.",
            "Insurance": "Annual premium split into monthly instalments.",
        },
    },
}
