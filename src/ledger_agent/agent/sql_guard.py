"""A read-only SQL sandbox for the agent. Defense in depth, enforced by SQLite itself - not by regexes.

Layers:
  1. READ-ONLY CONNECTION: for file databases the query runs on a separate `mode=ro` connection, so even a
     bug in the layers below cannot write.
  2. single statement only
  3. sqlite3 AUTHORIZER: allow SELECT / READ / FUNCTION / RECURSIVE only, and READ only on the ledger
     tables (transactions, accounts, and the v_transactions view over them) or on CTEs. INSERT, UPDATE, DELETE,
     PRAGMA, ATTACH, CREATE and reads of internal tables (LLM cache, memory, rules, sqlite_master) are
     denied by the engine at prepare time, whatever the query text looks like.
  4. PROGRESS HANDLER: aborts queries that run longer than the time budget (e.g. accidental cross joins)
  5. ROW LIMIT: results are capped and the agent is told they were truncated
Letting a model write SQL is powerful (arbitrary questions) and dangerous; these layers make it acceptable.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from dataclasses import dataclass

READABLE_TABLES = {"v_transactions", "transactions", "accounts"}

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)
_BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class SQLRejected(ValueError):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool

    def to_text(self, max_chars: int = 6000) -> str:
        if not self.rows:
            return "(no rows)"
        lines = [" | ".join(self.columns)]
        lines += [" | ".join("" if v is None else str(v) for v in r) for r in self.rows]
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... output truncated; aggregate with GROUP BY or add LIMIT ...]"
        if self.truncated:
            text += f"\n[only the first {len(self.rows)} rows shown; refine the query or aggregate]"
        return text


def _make_authorizer(protected: set[str]):
    """READ is denied for every real table/view except the readable ledger ones. Names that are not real
    tables (CTEs like `WITH m AS (...)`) are allowed - SQLite reports reads of CTEs like table reads."""

    def authorizer(action, arg1, arg2, db_name, source):
        if action not in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_DENY if (arg1 or "").lower() in protected else sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _BLOCKED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorizer


def _protected_names(conn: sqlite3.Connection) -> set[str]:
    names = {r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    return (names - READABLE_TABLES) | {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_sequence"}


def _clear_authorizer(conn: sqlite3.Connection) -> None:
    if sys.version_info >= (3, 11):
        conn.set_authorizer(None)
    else:  # Python 3.10 can't unset an authorizer; install an allow-all one instead
        conn.set_authorizer(lambda *a: sqlite3.SQLITE_OK)


def readonly_connection(conn: sqlite3.Connection) -> sqlite3.Connection | None:
    """A separate mode=ro connection to the same database file, or None for in-memory databases."""
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path:
        return None
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    ro.execute("PRAGMA query_only = ON")
    return ro


def run_readonly(conn: sqlite3.Connection, sql: str, row_limit: int = 200, timeout_ms: int = 2000) -> QueryResult:
    body = sql.strip().rstrip(";").strip()
    if not body:
        raise SQLRejected("empty query")
    if ";" in body:
        raise SQLRejected("only a single SELECT statement is allowed")
    ro = readonly_connection(conn)
    target = ro or conn
    deadline = time.monotonic() + timeout_ms / 1000
    target.set_authorizer(_make_authorizer(_protected_names(target)))
    target.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = target.execute(body)
        rows = cur.fetchmany(row_limit + 1)
        cols = [d[0] for d in cur.description or []]
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "not authorized" in msg or "prohibited" in msg or "readonly" in msg:
            raise SQLRejected("query not allowed: only SELECT from v_transactions is permitted") from e
        if "interrupted" in msg:
            raise SQLRejected(f"query exceeded {timeout_ms} ms; simplify it or aggregate") from e
        raise SQLRejected(f"SQL error: {msg}") from e
    finally:
        target.set_progress_handler(None, 0)
        if ro is not None:
            ro.close()
        else:
            _clear_authorizer(conn)
    return QueryResult(cols, [tuple(r) for r in rows[:row_limit]], truncated=len(rows) > row_limit)
