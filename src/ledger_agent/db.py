"""SQLite storage: connection setup, versioned migrations, transaction helper.

Design notes
- Money is stored as INTEGER minor units (paise). Floats cannot represent 0.10 exactly; ledgers must add up.
- Migrations are append-only and numbered. Never edit a shipped migration - add a new one.
- WAL mode lets the API read while a processing run writes.
- `transaction()` wraps a unit of work: a batch's results AND its checkpoint commit together or not at all.
  That is what makes processing resumable without double-applying work.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 - core schema
    """
    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        currency TEXT NOT NULL DEFAULT 'INR'
    );
    CREATE TABLE import_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signature TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        mapping_json TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('heuristic', 'llm', 'user')),
        uses INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        filename TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,
        profile_id INTEGER REFERENCES import_profiles(id),
        rows_total INTEGER NOT NULL DEFAULT 0,
        rows_new INTEGER NOT NULL DEFAULT 0,
        rows_duplicate INTEGER NOT NULL DEFAULT 0,
        rows_rejected INTEGER NOT NULL DEFAULT 0,
        balance_check TEXT,              -- 'ok' | 'mismatch' | 'no_balance_column'
        balance_mismatches INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        import_id INTEGER NOT NULL REFERENCES imports(id),
        date TEXT NOT NULL,                      -- ISO yyyy-mm-dd
        amount_minor INTEGER NOT NULL,           -- negative = money out (debit)
        description TEXT NOT NULL,
        merchant TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'other',
        balance_minor INTEGER,
        fingerprint TEXT NOT NULL UNIQUE,
        category TEXT,
        category_source TEXT CHECK (category_source IN ('rule', 'llm', 'user')),
        confidence REAL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'categorized', 'needs_review')),
        review_reason TEXT,
        rule_id INTEGER,
        llm_reason TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX ix_txn_status ON transactions(status, id);
    CREATE INDEX ix_txn_date ON transactions(date);
    CREATE INDEX ix_txn_merchant ON transactions(merchant);

    CREATE TABLE rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_type TEXT NOT NULL CHECK (pattern_type IN ('merchant', 'contains', 'regex')),
        pattern TEXT NOT NULL,
        direction TEXT CHECK (direction IN ('debit', 'credit')),
        category TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('user', 'compiled')),
        priority INTEGER NOT NULL DEFAULT 100,   -- lower runs first; user rules default to 10
        hits INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Verified labels: only a human (or explicit approval) writes here. The model never teaches itself.
    CREATE TABLE labels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id),
        merchant TEXT NOT NULL,
        description TEXT NOT NULL,
        direction TEXT NOT NULL,
        old_category TEXT,
        category TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('correction', 'confirmation')),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX ix_labels_merchant ON labels(merchant);

    CREATE TABLE runs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,          -- running | completed | paused_budget | failed
        checkpoint_id INTEGER NOT NULL DEFAULT 0,
        stats_json TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        finished_at TEXT
    );
    CREATE TABLE llm_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        purpose TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL,
        latency_ms INTEGER NOT NULL DEFAULT 0,
        cache_hit INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE llm_cache (
        key TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE memory_blocks (
        label TEXT PRIMARY KEY,
        description TEXT NOT NULL,
        value TEXT NOT NULL DEFAULT '',
        char_limit INTEGER NOT NULL
    );
    CREATE TABLE memory_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        importance REAL NOT NULL DEFAULT 5,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_accessed TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE conversation_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX ix_turns_conv ON conversation_turns(conversation_id, id);

    -- The only surface the Q&A agent's SQL tool can read. Amounts in major units for readability.
    CREATE VIEW v_transactions AS
        SELECT t.id, t.date, substr(t.date, 1, 7) AS month,
               t.amount_minor / 100.0 AS amount,
               CASE WHEN t.amount_minor < 0 THEN 'debit' ELSE 'credit' END AS direction,
               abs(t.amount_minor) / 100.0 AS abs_amount,
               t.merchant, t.channel, COALESCE(t.category, 'Uncategorized') AS category,
               t.status, a.name AS account, t.description
        FROM transactions t JOIN accounts a ON a.id = t.account_id;
    """,
]


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] or 0
    for version, sql in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        with transaction(conn):
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    return len(MIGRATIONS)


def _split_sql(script: str) -> list[str]:
    # executescript() would COMMIT implicitly and break atomicity, so we run statements one by one
    # inside our own transaction. sqlite3.complete_statement finds statement boundaries safely.
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any exception. Nested calls join the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
