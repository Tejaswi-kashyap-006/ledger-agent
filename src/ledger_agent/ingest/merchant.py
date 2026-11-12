"""Deterministic narration parser: extract (merchant, channel) from Indian bank narrations.

Examples it handles:
    UPI/DR/412345678901/ZOMATO LTD/YESB/zomato.payu@ybl/Payment   -> ZOMATO, upi
    UPI-SWIGGY-SWIGGY@ICICI-ICIC0DC0099-412345678901-UPI           -> SWIGGY, upi
    POS 512345XXXXXX1234 AMAZON PAY INDIA PVT                      -> AMAZON PAY, card
    NEFT CR-HDFC0000123-ACME TECHNOLOGIES PVT LTD-SALARY SEP       -> ACME TECHNOLOGIES, neft
    ACH D- BAJAJ FINANCE LTD-P401234567                            -> BAJAJ FINANCE, ach
    ATM WDL/HDFC ATM KORAMANGALA                                   -> ATM, atm

Why deterministic first: it is free, instant, testable and never hallucinates. The LLM only sees
what this parser couldn't resolve. Merchant keys are also what memory (labels, rules) is indexed by,
so they must be STABLE: the same payee must always produce the same key.
"""

from __future__ import annotations

import re

_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_NOISE_TOKENS = {
    "UPI", "DR", "CR", "P2A", "P2M", "PAYMENT", "PAY", "UPI PAYMENT", "NEFT", "IMPS", "RTGS", "POS", "ACH", "NACH",
    "ECS", "D", "C", "TO", "FROM", "BY", "TRANSFER", "TRF", "INB", "MB", "SENT", "RECEIVED", "COLLECT", "REQ",
    "BIL", "ONL", "BILLPAY", "BILLDESK", "YESB", "HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PYTM", "AIRP", "IBKL", "BARB", "PUNB", "NA", "NULL",
}
_SUFFIXES = re.compile(
    r"\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP|CORPORATION|INDIA|IN|CO|COMPANY|TECHNOLOGIES|TECHNOLOGY|SERVICES|SOLUTIONS|RETAIL|ONLINE)\b\.?",
)

CHANNEL_PATTERNS = [
    ("billpay", re.compile(r"\bBIL/ONL\b|\bBILLPAY\b|\bBILLDESK\b")),
    ("upi", re.compile(r"\bUPI\b")),
    ("atm", re.compile(r"\b(ATM|CASH WDL|NWD|ATW)\b")),
    ("card", re.compile(r"\b(POS|ECOM|CARD|VPS|IPS)\b|\d{4,6}X{4,}\d{4}")),
    ("neft", re.compile(r"\bNEFT\b")),
    ("imps", re.compile(r"\bIMPS\b")),
    ("rtgs", re.compile(r"\bRTGS\b")),
    ("ach", re.compile(r"\b(ACH|NACH|ECS)\b")),
    ("interest", re.compile(r"\b(INT\.?PD|INTEREST|INT CREDIT|SB INT)\b")),
    ("charges", re.compile(r"\b(CHRG|CHARGES|FEE|GST ON|SMS ALERT|AMC)\b")),
    ("cheque", re.compile(r"\b(CHQ|CHEQUE|CLG)\b")),
]


def detect_channel(desc: str) -> str:
    up = desc.upper()
    for name, pat in CHANNEL_PATTERNS:
        if pat.search(up):
            return name
    return "other"


_CITIES = re.compile(
    r"\b(BANGALORE|BENGALURU|BLR|MUMBAI|BOMBAY|DELHI|NEW DELHI|GURGAON|GURUGRAM|NOIDA|PUNE|HYDERABAD|CHENNAI|"
    r"KOLKATA|AHMEDABAD|KORAMANGALA|INDIRANAGAR|WHITEFIELD|HSR|IND)\b")


def canonical_merchant(name: str) -> str:
    """Stable key: uppercase, no legal suffixes, no city/locality tails, no punctuation, single spaces.
    'SWIGGY BANGALORE' (card) and 'SWIGGY' (UPI) must map to the same key, or memory fragments."""
    s = re.sub(r"[^A-Z0-9& ]", " ", name.upper())
    s = _SUFFIXES.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    stripped = _CITIES.sub(" ", s)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return (stripped or s)[:40]


def _candidate_tokens(desc: str) -> list[str]:
    up = desc.upper()
    up = re.sub(r"\d{4,6}X{4,}\d{4}", " ", up)          # masked card numbers
    parts = re.split(r"[/\-|:*]+", up)
    out = []
    for p in parts:
        words = p.split()
        while words and words[0] in _NOISE_TOKENS:      # "NEFT CR", "ACH D" -> drop channel words
            words.pop(0)
        p = " ".join(words)
        if not p or p in _NOISE_TOKENS or _IFSC.match(p) or "@" in p:
            continue
        if re.fullmatch(r"[\d\s.]+", p) or re.fullmatch(r"[A-Z]{0,3}\d{6,}", p):  # refs / txn ids
            continue
        out.append(p)
    return out


def extract_merchant(desc: str) -> tuple[str, str]:
    """Return (merchant_key, channel). merchant_key may be '' if nothing usable was found."""
    channel = detect_channel(desc)
    up = desc.upper()
    if channel == "atm":
        return "ATM", channel
    if channel == "interest":
        return "BANK INTEREST", channel
    if channel == "charges":
        return "BANK CHARGES", channel
    if "PAYMENT RECEIVED" in up:                      # credit-card side of a bill payment
        return "CARD PAYMENT RECEIVED", "transfer"

    if channel == "card":
        # "POS 512345XXXXXX1234 AMAZON PAY INDIA PVT" -> text after the card token / POS keyword
        body = re.sub(r"^.*?(POS|ECOM|VPS|IPS)\s+", "", up)
        body = re.sub(r"\d{4,6}X{4,}\d{4}", " ", body)
        return canonical_merchant(body), channel

    tokens = [t for t in _candidate_tokens(desc) if re.search(r"[A-Z]{3,}", t)]
    if channel == "upi":
        # the payee name is usually the first alphabetic segment; VPA local part is a fallback
        if tokens:
            return canonical_merchant(tokens[0]), channel
        vpa = re.search(r"([A-Z0-9._-]+)@[A-Z]+", up)
        return (canonical_merchant(vpa.group(1).split(".")[0]) if vpa else ""), channel
    if tokens:
        # NEFT/IMPS/ACH: first meaningful segment after the channel keyword
        return canonical_merchant(tokens[0]), channel
    return canonical_merchant(up)[:40], channel
