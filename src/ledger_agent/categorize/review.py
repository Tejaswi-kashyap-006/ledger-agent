"""Human-in-the-loop: the review queue and the write path of learning.

A correction does five things, atomically:
  1. fixes the transaction (source='user', confidence 1.0)
  2. stores a VERIFIED label (episodic memory; future few-shot examples)
  3. if it overturned a model answer, flags the model's identical answers for the same merchant for
     review (a confident mistake is rarely a one-off)
  4. invalidates compiled rules that contradict it (forgetting)
  5. compiles a new rule if enough consistent labels exist, and PROPAGATES it to the other
     unreviewed / model-labelled transactions of that merchant (one correction fixes many rows)

Two queues feed humans: the REVIEW queue (the model was unsure / a sensor fired) and the AUDIT sample
(the model was sure - spot-check it anyway, because confident errors are otherwise invisible).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from ledger_agent.categories import is_valid
from ledger_agent.categorize.rules import compile_from_labels, invalidate_conflicting
from ledger_agent.db import transaction


@dataclass
class CorrectionResult:
    transaction_id: int
    category: str
    rule_created: Optional[int]
    rules_invalidated: int
    propagated: int
    siblings_flagged: int = 0      # the model's identical answers for this payee sent back to review


def review_queue(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, date, amount_minor, merchant, description, category AS suggestion, confidence, review_reason,"
        " llm_reason FROM transactions WHERE status = 'needs_review' ORDER BY merchant, date LIMIT ?", (limit,)
    ).fetchall()


def audit_sample(conn: sqlite3.Connection, n: int = 5) -> list[sqlite3.Row]:
    """A SAMPLING SENSOR for silent errors. The review queue only ever sees what the model was unsure
    about; confidently-wrong answers never reach a human there and never get corrected. So we also audit
    auto-accepted model labels, one row per merchant, highest (rows affected x model doubt) first:
    one audit answer can then fix a whole merchant via sibling flags, examples and compiled rules."""
    return conn.execute(
        "SELECT t.id, t.date, t.amount_minor, t.merchant, t.description, t.category AS suggestion, t.confidence,"
        " 'audit' AS review_reason, t.llm_reason, g.n AS merchant_rows"
        " FROM transactions t JOIN ("
        "   SELECT merchant, category, MIN(id) AS id, COUNT(*) AS n, AVG(confidence) AS c FROM transactions"
        "   WHERE status='categorized' AND category_source='llm' AND merchant != ''"
        "   AND merchant NOT IN (SELECT merchant FROM labels) GROUP BY merchant, category) g ON g.id = t.id"
        " ORDER BY g.n * (1.05 - g.c) DESC, g.n DESC LIMIT ?", (n,)).fetchall()


def set_category(conn: sqlite3.Connection, txn_id: int, category: str, min_consistent: int = 2) -> CorrectionResult:
    if not is_valid(category):
        raise ValueError(f"unknown category {category!r}")
    with transaction(conn):
        t = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        if t is None:
            raise KeyError(f"no transaction {txn_id}")
        direction = "debit" if t["amount_minor"] < 0 else "credit"
        kind = "confirmation" if t["category"] == category else "correction"
        conn.execute("UPDATE transactions SET category=?, category_source='user', confidence=1.0, status='categorized',"
                     " review_reason=NULL, updated_at=datetime('now') WHERE id=?", (category, txn_id))
        siblings = 0
        if kind == "correction" and t["category_source"] == "llm" and t["category"]:
            # the model was confidently wrong once -> its other identical answers for this merchant are suspect
            sign = "< 0" if direction == "debit" else "> 0"
            siblings = conn.execute(
                f"UPDATE transactions SET status='needs_review', review_reason='sibling_of_correction',"
                f" updated_at=datetime('now') WHERE merchant=? AND amount_minor {sign} AND id != ?"
                f" AND category_source='llm' AND category=? AND status='categorized'",
                (t["merchant"], txn_id, t["category"])).rowcount
        conn.execute("INSERT INTO labels (transaction_id, merchant, description, direction, old_category, category, kind)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (txn_id, t["merchant"], t["description"], direction, t["category"], category, kind))
        invalidated = invalidate_conflicting(conn, t["merchant"], direction, category)
        rule_id = compile_from_labels(conn, t["merchant"], direction, min_consistent)
        propagated = 0
        if rule_id is not None:
            sign = "< 0" if direction == "debit" else "> 0"
            propagated = conn.execute(
                f"UPDATE transactions SET category=?, category_source='rule', confidence=1.0, status='categorized',"
                f" review_reason=NULL, rule_id=?, updated_at=datetime('now') WHERE merchant=? AND amount_minor {sign}"
                f" AND id != ? AND (status IN ('pending', 'needs_review') OR category_source = 'llm')",
                (category, rule_id, t["merchant"], txn_id)).rowcount
    return CorrectionResult(txn_id, category, rule_id, invalidated, propagated, siblings)


def accept_suggestion(conn: sqlite3.Connection, txn_id: int, min_consistent: int = 2) -> CorrectionResult:
    t = conn.execute("SELECT category FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if t is None or not t["category"]:
        raise ValueError(f"transaction {txn_id} has no suggestion to accept")
    return set_category(conn, txn_id, t["category"], min_consistent)
