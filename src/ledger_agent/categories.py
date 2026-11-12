"""The category chart. It is a closed set on purpose.

Because the LLM's output schema uses this list as an enum, the model *cannot* invent a category,
and a prompt-injected transaction cannot smuggle free text into the ledger. Constrained output
is one of the strongest guardrails available: it turns "please only answer X" into a guarantee.
"""

from __future__ import annotations

from typing import Literal, get_args

Category = Literal[
    "Income:Salary",
    "Income:Business",
    "Income:Interest & Dividends",
    "Income:Refund & Cashback",
    "Income:Other",
    "Housing:Rent",
    "Housing:Maintenance & Repairs",
    "Bills:Electricity & Water",
    "Bills:Mobile & Internet",
    "Bills:Gas",
    "Food:Groceries",
    "Food:Dining Out",
    "Food:Delivery",
    "Transport:Fuel",
    "Transport:Cab & Auto",
    "Transport:Public Transit",
    "Shopping:Online",
    "Shopping:Clothing",
    "Shopping:Electronics",
    "Health:Pharmacy",
    "Health:Doctor & Hospital",
    "Health:Fitness",
    "Entertainment:Subscriptions",
    "Entertainment:Movies & Events",
    "Travel:Flights & Trains",
    "Travel:Hotels",
    "Education",
    "Insurance",
    "Investments",
    "Loans & EMI",
    "Taxes & Government",
    "Fees & Bank Charges",
    "Cash Withdrawal",
    "Transfers:Self",
    "Transfers:To People",
    "Gifts & Donations",
    "Personal Care",
    "Other",
]

CATEGORIES: tuple[str, ...] = get_args(Category)
INCOME_PREFIX = "Income:"
# Categories that are movements of money, not spending. Reports exclude them from "expenses".
NON_EXPENSE = {"Transfers:Self", "Investments"}


def is_valid(category: str) -> bool:
    return category in CATEGORIES
