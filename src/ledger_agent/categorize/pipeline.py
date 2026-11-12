"""The processing loop: a resumable, budgeted, checkpointed batch run over pending transactions.

Per transaction, a CASCADE from cheapest/most-trusted to most-expensive/least-trusted:

    tripwire  - text looks like a prompt injection?        -> needs_review   (never let the model decide)
    rules     - user rules, then rules compiled from labels -> categorized    (confidence 1.0, 0 tokens)
    LLM       - batch structured output + verified examples -> categorized if confidence >= threshold
                                                              AND the direction sensor agrees
    otherwise                                               -> needs_review   (a human decides)

Loop properties (the long-horizon lessons from the course, applied):
  - each batch's writes + checkpoint commit in ONE transaction -> crash-safe, no double work
  - token budget checked before each LLM call -> run pauses as `paused_budget`, resumable later
  - LLM failure on a batch degrades to human review; it never stops the run
  - every run has an id, stats and a status you can inspect (`ledger runs`)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass

from ledger_agent.categories import INCOME_PREFIX
from ledger_agent.categorize.llm_categorizer import categorize_batch, retrieve_examples
from ledger_agent.categorize.rules import first_match, load_rules
from ledger_agent.config import Settings
from ledger_agent.db import transaction
from ledger_agent.llm.client import BudgetExceeded, LLMClient, LLMError
from ledger_agent.log import get_logger, run_id_var
from ledger_agent.memory import profile_text
from ledger_agent.security.redact import looks_like_injection

log = get_logger("pipeline")

# categories that legitimately occur on BOTH directions
_BIDIRECTIONAL = {"Transfers:Self", "Transfers:To People", "Investments", "Other", "Gifts & Donations", "Loans & EMI"}


@dataclass
class RunStats:
    processed: int = 0
    by_rule: int = 0
    by_llm: int = 0
    to_review: int = 0
    suspicious: int = 0
    llm_errors: int = 0
    direction_flags: int = 0
    batches: int = 0


@dataclass
class RunReport:
    run_id: str
    status: str
    stats: RunStats
    tokens: int


def direction_ok(category: str, amount_minor: int) -> bool:
    """Computational sensor on an inferential output: income categories on money-out (or spending
    categories on money-in, except refunds) are almost always wrong."""
    if category in _BIDIRECTIONAL:
        return True
    is_income = category.startswith(INCOME_PREFIX)
    return is_income if amount_minor > 0 else not is_income


def _mark(conn: sqlite3.Connection, txn_id: int, *, status: str, category=None, source=None, confidence=None,
          reason=None, rule_id=None, llm_reason=None) -> None:
    conn.execute("UPDATE transactions SET status=?, category=?, category_source=?, confidence=?, review_reason=?, "
                 "rule_id=?, llm_reason=?, updated_at=datetime('now') WHERE id=?",
                 (status, category, source, confidence, reason, rule_id, llm_reason, txn_id))


def _start_run(conn: sqlite3.Connection, run_id: str | None) -> tuple[str, int, RunStats]:
    if run_id:
        row = conn.execute("SELECT id, checkpoint_id, stats_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"no run {run_id}")
        conn.execute("UPDATE runs SET status='running', finished_at=NULL WHERE id=?", (run_id,))
        return run_id, row["checkpoint_id"], RunStats(**json.loads(row["stats_json"]))
    run_id = uuid.uuid4().hex[:12]
    conn.execute("INSERT INTO runs (id, kind, status) VALUES (?, 'categorize', 'running')", (run_id,))
    return run_id, 0, RunStats()


def process_pending(conn: sqlite3.Connection, llm: LLMClient | None, settings: Settings,
                    run_id: str | None = None, limit: int | None = None) -> RunReport:
    run_id, checkpoint, stats = _start_run(conn, run_id)
    token = run_id_var.set(run_id)
    status = "completed"
    start_tokens = llm.meter.usage.total if llm else 0
    try:
        rules = load_rules(conn)
        profile = profile_text(conn)
        while limit is None or stats.processed < limit:
            size = settings.batch_size if limit is None else min(settings.batch_size, limit - stats.processed)
            batch = conn.execute("SELECT * FROM transactions WHERE status = 'pending' AND id > ? ORDER BY id LIMIT ?",
                                 (checkpoint, size)).fetchall()
            if not batch:
                break
            snapshot = RunStats(**asdict(stats))
            try:
                with transaction(conn):
                    _process_batch(conn, llm, settings, batch, rules, profile, stats)
                    checkpoint = batch[-1]["id"]
                    stats.batches += 1
                    conn.execute("UPDATE runs SET checkpoint_id=?, stats_json=? WHERE id=?",
                                 (checkpoint, json.dumps(asdict(stats)), run_id))
            except BudgetExceeded as e:
                # the batch rolled back as a unit: nothing half-applied; `ledger process --resume` continues
                stats = snapshot
                status = "paused_budget"
                log.warning("budget exhausted; pausing run", extra={"detail": str(e)})
                break
    except Exception:
        status = "failed"
        log.exception("run failed")
        raise
    finally:
        conn.execute("UPDATE runs SET status=?, stats_json=?, finished_at=datetime('now') WHERE id=?",
                     (status, json.dumps(asdict(stats)), run_id))
        run_id_var.reset(token)
    used = (llm.meter.usage.total - start_tokens) if llm else 0
    log.info("run finished", extra={"run": run_id, "status": status, **asdict(stats), "tokens": used})
    return RunReport(run_id, status, stats, used)


def _process_batch(conn: sqlite3.Connection, llm: LLMClient | None, settings: Settings, batch: list[sqlite3.Row],
                   rules: list, profile: str, stats: RunStats) -> None:
    for_llm = []
    for t in batch:
        stats.processed += 1
        if looks_like_injection(t["description"]):
            stats.suspicious += 1
            stats.to_review += 1
            _mark(conn, t["id"], status="needs_review", reason="suspicious_text")
            continue
        rule = first_match(rules, t["merchant"], t["description"], t["amount_minor"])
        if rule:
            stats.by_rule += 1
            conn.execute("UPDATE rules SET hits = hits + 1 WHERE id = ?", (rule.id,))
            _mark(conn, t["id"], status="categorized", category=rule.category, source="rule", confidence=1.0,
                  rule_id=rule.id)
            continue
        for_llm.append(t)

    if not for_llm:
        return
    if llm is None:
        for t in for_llm:
            stats.to_review += 1
            _mark(conn, t["id"], status="needs_review", reason="no_llm")
        return

    try:
        examples = retrieve_examples(conn, for_llm, settings.few_shot_examples)
        results = categorize_batch(llm, for_llm, examples, profile, settings.redact_pii)
    except LLMError as e:
        log.warning("batch failed; routing to review", extra={"error": str(e)[:200], "size": len(for_llm)})
        stats.llm_errors += 1
        results = {}

    for t in for_llm:
        r = results.get(t["id"])
        if r is None:
            stats.to_review += 1
            _mark(conn, t["id"], status="needs_review", reason="llm_no_answer")
        elif not direction_ok(r.category, t["amount_minor"]):
            stats.direction_flags += 1
            stats.to_review += 1
            _mark(conn, t["id"], status="needs_review", category=r.category, source="llm", confidence=r.confidence,
                  reason="direction_mismatch", llm_reason=r.reason)
        elif r.confidence < settings.auto_accept_confidence:
            stats.to_review += 1
            _mark(conn, t["id"], status="needs_review", category=r.category, source="llm", confidence=r.confidence,
                  reason="low_confidence", llm_reason=r.reason)
        else:
            stats.by_llm += 1
            _mark(conn, t["id"], status="categorized", category=r.category, source="llm", confidence=r.confidence,
                  llm_reason=r.reason)
