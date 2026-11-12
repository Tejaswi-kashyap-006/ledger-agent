"""Robust CSV reading for bank exports.

Real bank exports are not clean CSVs: they start with 5-20 lines of preamble (account holder,
address, statement period), use odd encodings, sometimes ';' delimiters, and end with footer
text ("*** End of statement ***", totals). This module finds the actual table.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass

HEADER_HINTS = re.compile(
    r"date|narration|description|particulars|details|remarks|withdrawal|debit|deposit|credit|amount|balance|"
    r"chq|ref|value dt|transaction",
    re.I,
)


@dataclass
class RawTable:
    header: list[str]
    rows: list[list[str]]
    preamble: list[str]
    sha256: str

    @property
    def signature(self) -> str:
        """Identity of the FORMAT (not the content): same bank export layout -> same signature.
        Used as the key for learned import profiles (procedural memory)."""
        norm = "|".join(re.sub(r"[^a-z]", "", h.lower()) for h in self.header)
        return hashlib.sha256(norm.encode()).hexdigest()[:16]


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _header_score(row: list[str]) -> int:
    cells = [c.strip() for c in row if c.strip()]
    if len(cells) < 3:
        return 0
    return sum(1 for c in cells if HEADER_HINTS.search(c) and len(c) < 40)


def _fallback_header(rows: list[list[str]]) -> int:
    """Unfamiliar column names: take the first all-text row of >= 3 cells followed by a row of the same
    width that contains digits (i.e. looks like data). The profile step decides what the columns mean."""
    for i, row in enumerate(rows[:-1]):
        cells = [c.strip() for c in row if c.strip()]
        nxt = [c.strip() for c in rows[i + 1] if c.strip()]
        if (len(cells) >= 3 and not any(re.search(r"\d", c) for c in cells)
                and len(nxt) == len(cells) and any(re.search(r"\d", c) for c in nxt)):
            return i
    return -1


def read_table(data: bytes, max_scan: int = 40) -> RawTable:
    text = decode(data)
    delim = _sniff_delimiter("\n".join(text.splitlines()[:max_scan]))
    all_rows = list(csv.reader(io.StringIO(text), delimiter=delim))

    # header = the row in the first `max_scan` rows that looks most like column names
    best_i, best_score = -1, 0
    for i, row in enumerate(all_rows[:max_scan]):
        score = _header_score(row)
        if score > best_score:
            best_i, best_score = i, score
    if best_i < 0 or best_score < 2:
        best_i = _fallback_header(all_rows[:max_scan])
    if best_i < 0:
        raise ValueError("Could not find a header row (expected columns like Date / Narration / Amount).")

    header = [h.strip() for h in all_rows[best_i]]
    width = len(header)
    rows = []
    for row in all_rows[best_i + 1:]:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        if len([c for c in cells if c]) < 2:       # footer / separator lines
            continue
        cells = (cells + [""] * width)[:width]
        rows.append(cells)
    preamble = [" ".join(r).strip() for r in all_rows[:best_i] if any(c.strip() for c in r)]
    return RawTable(header=header, rows=rows, preamble=preamble, sha256=hashlib.sha256(data).hexdigest())
