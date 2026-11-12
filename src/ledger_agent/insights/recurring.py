"""Recurring payment (subscription / EMI / rent) detection - pure statistics, no LLM.

A merchant is recurring when its debits are (a) regular in time and (b) stable in amount. Transfers to your
own accounts (e.g. the monthly credit-card bill payment) are excluded: moving money isn't a charge.
We also flag PRICE CHANGES (latest charge noticeably above the typical one), which is one of the
most useful things a bookkeeper can tell you and needs zero AI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

CADENCES = [("weekly", 7, 2), ("monthly", 30, 4), ("quarterly", 91, 8), ("yearly", 365, 15)]
_MONTHLY_FACTOR = {"weekly": 52 / 12, "monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12}


@dataclass
class Recurring:
    merchant: str
    category: str
    cadence: str
    occurrences: int
    typical_amount_minor: int
    last_amount_minor: int
    last_date: str
    next_expected: str
    monthly_cost_minor: int
    price_change_pct: float      # last vs typical; > 0 means it got more expensive


def _cadence(intervals: list[int]) -> str | None:
    if not intervals:
        return None
    m = median(intervals)
    for name, days, tol in CADENCES:
        if abs(m - days) <= tol:
            regular = sum(1 for i in intervals if abs(i - days) <= tol * 1.5) / len(intervals)
            return name if regular >= 0.75 else None
    return None


def detect_recurring(conn: sqlite3.Connection, min_occurrences: int = 3) -> list[Recurring]:
    rows = conn.execute("SELECT merchant, date, amount_minor, COALESCE(category, 'Other') AS category FROM transactions "
                        "WHERE amount_minor < 0 AND merchant NOT IN ('', 'ATM', 'BANK CHARGES')"
                        " AND COALESCE(category, '') != 'Transfers:Self' ORDER BY merchant, date")\
        .fetchall()
    by_merchant: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_merchant.setdefault(r["merchant"], []).append(r)

    out = []
    for merchant, txns in by_merchant.items():
        if len(txns) < min_occurrences:
            continue
        dates = [date.fromisoformat(t["date"]) for t in txns]
        intervals = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        cadence = _cadence(intervals)
        if cadence is None:
            continue
        amounts = [abs(t["amount_minor"]) for t in txns]
        typical = int(median(amounts[:-1] or amounts))
        mad = median(abs(a - typical) for a in amounts[:-1] or amounts)
        if typical == 0 or mad / typical > 0.15:       # amounts all over the place -> just a frequent merchant
            continue
        last = amounts[-1]
        step = int(median(intervals))
        out.append(Recurring(
            merchant=merchant, category=txns[-1]["category"], cadence=cadence, occurrences=len(txns),
            typical_amount_minor=typical, last_amount_minor=last, last_date=dates[-1].isoformat(),
            next_expected=(dates[-1] + timedelta(days=step)).isoformat(),
            monthly_cost_minor=int(last * _MONTHLY_FACTOR[cadence]),
            price_change_pct=round((last - typical) / typical * 100, 1),
        ))
    return sorted(out, key=lambda r: r.monthly_cost_minor, reverse=True)
