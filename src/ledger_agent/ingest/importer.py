"""Import a statement file: read -> resolve profile -> parse -> de-duplicate -> store. One DB transaction."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from ledger_agent.db import transaction
from ledger_agent.ingest.csv_reader import read_table
from ledger_agent.ingest.merchant import extract_merchant
from ledger_agent.ingest.normalize import fingerprint, normalize_description
from ledger_agent.ingest.profiles import resolve_profile
from ledger_agent.llm.client import LLMClient
from ledger_agent.log import get_logger

log = get_logger("import")


@dataclass
class ImportResult:
    import_id: int
    account: str
    profile_name: str
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_rejected: int
    balance_check: str
    balance_mismatches: int
    rejects: list[tuple[int, str]]


def get_or_create_account(conn: sqlite3.Connection, name: str, currency: str = "INR") -> int:
    conn.execute("INSERT OR IGNORE INTO accounts (name, currency) VALUES (?, ?)", (name, currency))
    return conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()["id"]


def import_statement(conn: sqlite3.Connection, llm: LLMClient | None, account: str, filename: str,
                     data: bytes, currency: str = "INR") -> ImportResult:
    table = read_table(data)
    with transaction(conn):
        account_id = get_or_create_account(conn, account, currency)
        profile_id, profile, check = resolve_profile(conn, llm, table)
        cur = conn.execute(
            "INSERT INTO imports (account_id, filename, file_sha256, profile_id, rows_total, balance_check,"
            " balance_mismatches) VALUES (?,?,?,?,?,?,?) RETURNING id",
            (account_id, filename, table.sha256, profile_id, len(table.rows), check.balance_check,
             check.balance_mismatches))
        import_id = cur.fetchone()["id"]

        seen: Counter = Counter()
        new = dup = 0
        for r in check.parsed:
            desc = normalize_description(r.description)
            key = (r.date, r.amount_minor, desc.upper())
            occurrence = seen[key]
            seen[key] += 1
            fp = fingerprint(account_id, r.date, r.amount_minor, desc, occurrence)
            merchant, channel = extract_merchant(desc)
            ins = conn.execute(
                "INSERT OR IGNORE INTO transactions (account_id, import_id, date, amount_minor, description, merchant,"
                " channel, balance_minor, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, import_id, r.date.isoformat(), r.amount_minor, desc, merchant, channel,
                 r.balance_minor, fp))
            if ins.rowcount == 1:
                new += 1
            else:
                dup += 1
        conn.execute("UPDATE imports SET rows_new=?, rows_duplicate=?, rows_rejected=? WHERE id=?",
                     (new, dup, len(check.rejects), import_id))

    log.info("imported statement", extra={"file": filename, "new": new, "duplicates": dup,
                                          "rejected": len(check.rejects), "balance": check.balance_check})
    return ImportResult(import_id, account, profile.name, len(table.rows), new, dup, len(check.rejects),
                        check.balance_check, check.balance_mismatches, check.rejects[:20])
