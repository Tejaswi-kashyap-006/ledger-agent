"""Parsing the ugly parts of bank exports: dates, amounts, and a stable identity for each row."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = [
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y",
    "%d %b %y", "%d %B %Y", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%b %d, %Y",
]

_CURRENCY = re.compile(r"(₹|rs\.?|inr)", re.I)


def parse_date(value: str, fmt: str | None = None) -> date:
    value = value.strip()
    if fmt:
        return datetime.strptime(value, fmt).date()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(value, f).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date {value!r}")


def detect_date_format(samples: list[str]) -> str | None:
    """The first format that parses EVERY sample. Order encodes the day-first preference (India/UK);
    samples like 13/02/2026 disambiguate automatically because %m/%d fails on them."""
    samples = [s.strip() for s in samples if s and s.strip()]
    for f in DATE_FORMATS:
        try:
            for s in samples:
                datetime.strptime(s, f)
            return f
        except ValueError:
            continue
    return None


def parse_amount_minor(value: str) -> int | None:
    """'1,23,456.78' -> 12345678 ; '(250.00)' -> -25000 ; '500 Dr' -> -50000 ; '' -> None.
    Decimal, never float: float('0.1')*3 != 0.3, and ledgers must balance to the paisa."""
    if value is None:
        return None
    s = _CURRENCY.sub("", str(value)).strip().replace(",", "").replace(" ", "")
    if not s or s in {"-", "--"}:
        return None
    sign = 1
    if s.startswith("(") and s.endswith(")"):
        sign, s = -1, s[1:-1]
    low = s.lower()
    if low.endswith("dr"):
        sign, s = -1, s[:-2]
    elif low.endswith("cr"):
        s = s[:-2]
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"unrecognized amount {value!r}") from e
    return sign * int((d * 100).quantize(Decimal("1")))


def normalize_description(desc: str) -> str:
    return re.sub(r"\s+", " ", desc).strip()


def fingerprint(account_id: int, day: date, amount_minor: int, description: str, occurrence: int) -> str:
    """Identity of a transaction for de-duplication across overlapping statement imports.

    `occurrence` = how many identical (date, amount, description) rows came before this one in the SAME
    file. Two genuine ₹20 chai payments on the same day stay two rows; importing the file twice doesn't."""
    key = f"{account_id}|{day.isoformat()}|{amount_minor}|{normalize_description(description).upper()}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()


def format_money(minor: int, currency: str = "INR") -> str:
    sign = "-" if minor < 0 else ""
    major, paise = divmod(abs(minor), 100)
    # Indian digit grouping: 12,34,567.89
    s = str(major)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}(?=(?:\d{2})*$)", head))
        s = f"{head},{tail}"
    symbol = "₹" if currency == "INR" else f"{currency} "
    return f"{sign}{symbol}{s}.{paise:02d}"
