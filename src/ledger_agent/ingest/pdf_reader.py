"""PDF bank statements -> the same RawTable the CSV reader produces.

Everything after this step (profile learning, the balance sensor, de-duplication) is unchanged, which
is the point: a PDF is just another way of laying out the same table. The extra work is rebuilding the
columns, because a PDF has no cells, only text drawn at x positions:

    1. extract each page's text in layout mode (pypdf keeps horizontal positions as spaces)
    2. split every line into chunks at runs of 2+ spaces, remembering where each chunk starts and ends
    3. find the header line (same keyword score as CSV), and take its chunks as the column spans
    4. put every chunk of a data line into the column it overlaps most (numbers are usually
       right-aligned, so overlap beats left-edge matching), or the nearest one
    5. a line with no date that sits directly under a row (no blank line between them) is the
       wrapped tail of that row's narration; a repeated page header is skipped

A mis-assigned column doesn't slip through: the profile validator re-parses every row and checks the
running balance to the paisa, so a bad reconstruction makes the import fail loudly instead.

Scanned statements have no text layer. They're refused with a clear message (a vision step would
go here). Password-protected PDFs, which many Indian banks send, open with the password given.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

from ledger_agent.ingest.csv_reader import RawTable, _header_score

_CHUNK = re.compile(r"\S+(?: \S+)*")          # words separated by single spaces
_DATEISH = re.compile(r"^\d{1,2}[-/ .](\d{1,2}|[A-Za-z]{3})[-/ .]\d{2,4}$|^\d{4}-\d{2}-\d{2}$")


class PdfPasswordRequired(ValueError):
    pass


@dataclass
class _Chunk:
    start: int
    end: int
    text: str


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF-")


def _chunks(line: str) -> list[_Chunk]:
    out: list[_Chunk] = []
    for m in _CHUNK.finditer(line):
        # a single space inside a chunk is part of the text; 2+ spaces separate cells
        parts = re.split(r"( {2,})", m.group(0))
        pos = m.start()
        for p in parts:
            if p and not p.isspace():
                out.append(_Chunk(pos, pos + len(p), p))
            pos += len(p)
    return out


def _rejoin(head: str, tail: str) -> str:
    """Banks wrap narrations after a separator (UPI/DR/123/NAME/ + bank@upi) or at a space. Rejoining
    without a space after a separator restores the narration as the CSV export spells it, which keeps
    fingerprints, merchants and de-duplication identical across the two formats."""
    if not head:
        return tail
    return head + tail if head.endswith(("/", "-", "@", ".", "_", ":")) else f"{head} {tail}"


_NUMBER = re.compile(r"^-?[\d,]+\.\d{2}( ?(Dr|Cr))?$", re.I)


def _column_for(chunk: _Chunk, spans: list[tuple[int, int]]) -> int:
    if _NUMBER.match(chunk.text):
        # amounts are right-aligned: a short "1.00" can sit nearer the next column's left edge than its own
        return min(range(len(spans)), key=lambda i: abs(chunk.end - spans[i][1]))
    overlaps = [max(0, min(chunk.end, e) - max(chunk.start, s)) for s, e in spans]
    best = max(range(len(spans)), key=lambda i: overlaps[i])
    if overlaps[best] > 0:
        return best
    gaps = [min(abs(chunk.start - e), abs(chunk.end - s)) for s, e in spans]
    return min(range(len(spans)), key=lambda i: gaps[i])


def extract_lines(data: bytes, password: str | None = None) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as e:
        raise ValueError(f"This file isn't a readable PDF ({e}).") from e
    if reader.is_encrypted:
        if not password:
            raise PdfPasswordRequired("This PDF is password-protected. Banks usually send statements locked with "
                                      "a password (often based on your name, date of birth or customer ID): "
                                      "enter it and import again.")
        try:
            ok = reader.decrypt(password)
        except Exception as e:  # noqa: BLE001 - e.g. AES without the crypto extra installed
            raise ValueError(f"Couldn't open this PDF: {e}") from e
        if not ok:
            raise PdfPasswordRequired("That password didn't open the PDF. Check it and try again.")
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        lines.extend(text.splitlines())
        lines.append("")                        # page break = a gap, so rows never continue across pages
    if not any(line.strip() for line in lines):
        raise ValueError("This PDF has no text layer (it looks like a scan or a photo). Scanned statements "
                         "aren't supported yet: download the statement from net banking as a PDF or CSV.")
    return lines


def read_pdf_table(data: bytes, password: str | None = None, max_scan: int = 120) -> RawTable:
    lines = extract_lines(data, password)

    best_i, best_score = -1, 0
    for i, line in enumerate(lines[:max_scan]):
        score = _header_score([c.text for c in _chunks(line)])
        if score > best_score:
            best_i, best_score = i, score
    if best_i < 0 or best_score < 3:
        raise ValueError("Couldn't find the transaction table in this PDF (expected a header row with columns "
                         "like Date / Narration / Withdrawal / Deposit / Balance).")

    head = _chunks(lines[best_i])
    header = [c.text for c in head]
    spans = [(c.start, c.end) for c in head]
    norm_header = [h.lower() for h in header]
    width = len(header)
    date_col = next((i for i, h in enumerate(norm_header) if "date" in h), 0)

    rows: list[list[str]] = []
    can_continue = False                  # True only directly under a row (or under its wrapped tail)
    for line in lines[best_i + 1:]:
        chunks = _chunks(line)
        if not chunks or [c.text.lower() for c in chunks] == norm_header:   # gap, or header on a later page
            can_continue = False
            continue
        cells = [""] * width
        for c in chunks:
            col = _column_for(c, spans)
            cells[col] = f"{cells[col]} {c.text}".strip()
        has_date = bool(_DATEISH.match(cells[date_col]))
        filled = [i for i, v in enumerate(cells) if v]
        if not has_date and can_continue and not any(_NUMBER.match(c.text) for c in chunks):
            for i in filled:                                     # wrapped narration: glue onto the row above
                rows[-1][i] = _rejoin(rows[-1][i], cells[i])
        elif len(filled) >= 2 and has_date:
            rows.append(cells)
            can_continue = True
        else:
            # not a row: page footers, totals, "*** End of Statement ***". Nothing below continues a row.
            can_continue = False

    preamble = [" ".join(c.text for c in _chunks(line)) for line in lines[:best_i] if line.strip()]
    return RawTable(header=header, rows=rows, preamble=preamble, sha256=hashlib.sha256(data).hexdigest())
