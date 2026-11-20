"""Transfers between the household's own accounts, matched the way a bookkeeper does it.

Paying the credit card bill from savings shows up twice: a debit in the savings statement and an equal
credit in the card statement a day or two later. Neither side is spending, but to a model reading one
line at a time, "ICICI CREDIT CARD -18,450" looks like an EMI, and it says so confidently. That error
inflates every spending total, and confidence-based review never surfaces it.

This is a computational check, so it needs no model and no household memory: an entry is a transfer to
self when ANOTHER account holds exactly the opposite amount within a few days, and the pairing is unique
from both sides. Uniqueness is the guard against coincidences (two ₹500 payments and one ₹500 refund
pair up with nothing). The match runs after the rules (your rules still win) and before the model.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

TRANSFER_CATEGORY = "Transfers:Self"
WINDOW_DAYS = 4


def _candidates(conn: sqlite3.Connection, txn_id: int, account_id: int, date: str, amount_minor: int) -> list:
    return conn.execute(
        "SELECT id, account_id, date, amount_minor, status, category_source, review_reason FROM transactions"
        " WHERE account_id != ? AND amount_minor = ? AND id != ?"
        " AND ABS(julianday(date) - julianday(?)) <= ?",
        (account_id, -amount_minor, txn_id, date, WINDOW_DAYS)).fetchall()


def find_counterpart(conn: sqlite3.Connection, txn: sqlite3.Row) -> Optional[sqlite3.Row]:
    """The one entry in another account that mirrors `txn`, or None if there is none or it's ambiguous."""
    if txn["amount_minor"] == 0:
        return None
    found = _candidates(conn, txn["id"], txn["account_id"], txn["date"], txn["amount_minor"])
    if len(found) != 1:
        return None
    other = found[0]
    back = _candidates(conn, other["id"], other["account_id"], other["date"], other["amount_minor"])
    if [r["id"] for r in back] != [txn["id"]]:
        return None
    if other["category_source"] == "user" or other["review_reason"] == "suspicious_text":
        return None                      # a human decision, or text we refuse to act on, is never overridden
    return other


def counterpart_can_follow(other: sqlite3.Row) -> bool:
    """Whether the matched entry may be re-posted as a transfer too. Pending entries are left for their own
    batch (they will match back); rule-posted ones keep the rule's answer; model answers are overturned."""
    return other["status"] != "pending" and other["category_source"] in ("llm", None)
