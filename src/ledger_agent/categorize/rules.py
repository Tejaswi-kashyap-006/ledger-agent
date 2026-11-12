"""Deterministic rules, and the compiler that turns human corrections into rules.

The memory lifecycle this module implements:

    human correction --(episodic memory: labels table)--> few-shot example for the LLM (soft)
    N consistent corrections for a merchant --(compile)--> rule (hard, deterministic, free, auditable)
    a later contradicting correction --(invalidate)--> compiled rule deactivated (forgetting)

This is the harness "ratchet" applied to data: an inferential decision that humans keep making
the same way graduates into a computational control, and the LLM is never asked again.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from ledger_agent.categories import is_valid
from ledger_agent.log import get_logger

log = get_logger("rules")
USER_PRIORITY, COMPILED_PRIORITY = 10, 100


@dataclass
class Rule:
    id: int
    pattern_type: str
    pattern: str
    direction: Optional[str]
    category: str
    source: str
    priority: int


@lru_cache(maxsize=512)
def _regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


def load_rules(conn: sqlite3.Connection) -> list[Rule]:
    rows = conn.execute("SELECT id, pattern_type, pattern, direction, category, source, priority FROM rules "
                        "WHERE active = 1 ORDER BY priority, id").fetchall()
    return [Rule(**dict(r)) for r in rows]


def matches(rule: Rule, merchant: str, description: str, amount_minor: int) -> bool:
    direction = "debit" if amount_minor < 0 else "credit"
    if rule.direction and rule.direction != direction:
        return False
    if rule.pattern_type == "merchant":
        return merchant == rule.pattern
    if rule.pattern_type == "contains":
        return rule.pattern.upper() in description.upper()
    return bool(_regex(rule.pattern).search(description))


def first_match(rules: list[Rule], merchant: str, description: str, amount_minor: int) -> Optional[Rule]:
    return next((r for r in rules if matches(r, merchant, description, amount_minor)), None)


def add_rule(conn: sqlite3.Connection, pattern_type: str, pattern: str, category: str,
             direction: Optional[str] = None, source: str = "user", priority: Optional[int] = None) -> int:
    if not is_valid(category):
        raise ValueError(f"unknown category {category!r}")
    if pattern_type not in ("merchant", "contains", "regex"):
        raise ValueError("pattern_type must be merchant | contains | regex")
    if pattern_type == "regex":
        if len(pattern) > 200:
            raise ValueError("regex too long")
        re.compile(pattern)  # fail fast on invalid patterns
    prio = priority if priority is not None else (USER_PRIORITY if source == "user" else COMPILED_PRIORITY)
    cur = conn.execute("INSERT INTO rules (pattern_type, pattern, direction, category, source, priority) "
                       "VALUES (?,?,?,?,?,?) RETURNING id", (pattern_type, pattern, direction, category, source, prio))
    return cur.fetchone()["id"]


def compile_from_labels(conn: sqlite3.Connection, merchant: str, direction: str, min_consistent: int) -> Optional[int]:
    """If the last `min_consistent` verified labels for (merchant, direction) agree, ensure a compiled rule.
    Returns the id of a newly created rule, or None."""
    if not merchant:
        return None
    labels = conn.execute("SELECT category FROM labels WHERE merchant = ? AND direction = ? ORDER BY id DESC LIMIT ?",
                          (merchant, direction, min_consistent)).fetchall()
    if len(labels) < min_consistent or len({r["category"] for r in labels}) != 1:
        return None
    category = labels[0]["category"]
    existing = conn.execute("SELECT id, category FROM rules WHERE source = 'compiled' AND pattern_type = 'merchant' "
                            "AND pattern = ? AND direction = ? AND active = 1", (merchant, direction)).fetchone()
    if existing and existing["category"] == category:
        return None
    if existing:
        conn.execute("UPDATE rules SET active = 0 WHERE id = ?", (existing["id"],))
    rule_id = add_rule(conn, "merchant", merchant, category, direction, source="compiled")
    log.info("compiled rule from corrections", extra={"merchant": merchant, "category": category, "rule_id": rule_id})
    return rule_id


def invalidate_conflicting(conn: sqlite3.Connection, merchant: str, direction: str, category: str) -> int:
    """A human just disagreed with a compiled rule -> stop trusting it (forgetting)."""
    cur = conn.execute("UPDATE rules SET active = 0 WHERE source = 'compiled' AND pattern_type = 'merchant' "
                       "AND pattern = ? AND direction = ? AND category != ? AND active = 1",
                       (merchant, direction, category))
    return cur.rowcount
