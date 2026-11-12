"""Application service: the one facade the CLI and the HTTP API both use.

Owns the wiring (settings, DB connection, LLM client) and per-operation budgets. Keeping this
layer thin and shared means the CLI and API can never drift into different behaviour.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from typing import Optional

from ledger_agent import memory
from ledger_agent.agent.loop import AgentAnswer, ask
from ledger_agent.categorize.pipeline import RunReport, process_pending
from ledger_agent.categorize.review import (CorrectionResult, accept_suggestion, audit_sample, review_queue,
                                           set_category)
from ledger_agent.categorize.rules import add_rule
from ledger_agent.config import Settings, get_settings
from ledger_agent.db import connect
from ledger_agent.ingest.importer import ImportResult, import_statement
from ledger_agent.insights.recurring import Recurring, detect_recurring
from ledger_agent.insights.report import MonthlyReport, write_report
from ledger_agent.llm.client import LLMClient, OpenAIClient, UsageMeter

_AUTO = object()


class LedgerService:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None | object = _AUTO,
                 conn: sqlite3.Connection | None = None):
        self.settings = settings or get_settings()
        self.conn = conn or connect(self.settings.db_path)
        memory.ensure_blocks(self.conn)
        if llm is _AUTO:
            llm = OpenAIClient(self.settings, self.conn) if os.environ.get("OPENAI_API_KEY") else None
        self.llm: Optional[LLMClient] = llm  # type: ignore[assignment]

    def close(self) -> None:
        self.conn.close()

    def _budget(self, max_tokens: int) -> None:
        if self.llm is not None:
            self.llm.meter = UsageMeter(max_tokens)

    # --------------------------------------------------------------------- ingest & process
    def import_file(self, account: str, filename: str, data: bytes) -> ImportResult:
        self._budget(50_000)
        return import_statement(self.conn, self.llm, account, filename, data, self.settings.currency)

    def process(self, run_id: str | None = None, limit: int | None = None) -> RunReport:
        self._budget(self.settings.max_tokens_per_run)
        return process_pending(self.conn, self.llm, self.settings, run_id=run_id, limit=limit)

    # --------------------------------------------------------------------- review & rules
    def review_queue(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in review_queue(self.conn, limit)]

    def audit_sample(self, n: int = 5) -> list[dict]:
        return [dict(r) for r in audit_sample(self.conn, n)]

    def set_category(self, txn_id: int, category: str) -> CorrectionResult:
        return set_category(self.conn, txn_id, category, self.settings.rule_min_consistent_corrections)

    def accept(self, txn_id: int) -> CorrectionResult:
        return accept_suggestion(self.conn, txn_id, self.settings.rule_min_consistent_corrections)

    def add_rule(self, pattern_type: str, pattern: str, category: str, direction: str | None = None) -> int:
        return add_rule(self.conn, pattern_type, pattern.upper() if pattern_type == "merchant" else pattern,
                        category, direction)

    def rules(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM rules WHERE active = 1 ORDER BY priority, id")]

    # --------------------------------------------------------------------- agent & insights
    def ask(self, question: str, conversation_id: str | None = None) -> AgentAnswer:
        if self.llm is None:
            raise RuntimeError("The Q&A agent needs OPENAI_API_KEY.")
        self._budget(int(self.settings.agent_max_tokens_per_question * 1.5))
        return ask(self.conn, self.llm, self.settings, question, conversation_id)

    def report(self, month: str) -> MonthlyReport:
        self._budget(60_000)
        return write_report(self.conn, self.llm, month, self.settings)

    def subscriptions(self) -> list[Recurring]:
        return detect_recurring(self.conn)

    def set_memory(self, block: str, text: str) -> str:
        memory.ensure_blocks(self.conn)
        current = self.conn.execute("SELECT value FROM memory_blocks WHERE label = ?", (block,)).fetchone()
        if current is None:
            raise ValueError(f"unknown block {block!r}")
        return memory.update_block(self.conn, block, current["value"], text) if current["value"] else \
            memory.update_block(self.conn, block, "", text)

    def memory_view(self) -> dict:
        return {"blocks": memory.render_blocks(self.conn),
                "facts": [dict(r) for r in self.conn.execute(
                    "SELECT id, text, importance, created_at FROM memory_facts WHERE active = 1 ORDER BY id")]}

    # --------------------------------------------------------------------- read models for the UI
    def accounts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT a.id, a.name, a.currency, COUNT(t.id) AS transactions FROM accounts a"
            " LEFT JOIN transactions t ON t.account_id = a.id GROUP BY a.id ORDER BY a.name")]

    def months(self) -> list[str]:
        return [r["m"] for r in self.conn.execute(
            "SELECT DISTINCT substr(date, 1, 7) AS m FROM transactions ORDER BY m DESC")]

    def trend(self) -> list[dict]:
        """Money in vs money out per month, with the same definitions as the monthly report:
        in = Income:* credits; out = debits excluding transfers-to-self and investments."""
        from ledger_agent.categories import INCOME_PREFIX, NON_EXPENSE
        excluded = ",".join("?" * len(NON_EXPENSE))
        rows = self.conn.execute(
            "SELECT substr(date, 1, 7) AS month,"
            " SUM(CASE WHEN amount_minor > 0 AND COALESCE(category, '') LIKE ? THEN amount_minor ELSE 0 END) AS money_in,"
            f" SUM(CASE WHEN amount_minor < 0 AND COALESCE(category, '') NOT IN ({excluded})"
            "   THEN -amount_minor ELSE 0 END) AS money_out,"
            " SUM(status != 'categorized') AS unreviewed"
            " FROM transactions GROUP BY month ORDER BY month",
            (INCOME_PREFIX + "%", *sorted(NON_EXPENSE))).fetchall()
        return [dict(r) for r in rows]

    def memory_blocks(self) -> list[dict]:
        memory.ensure_blocks(self.conn)
        return [dict(r) for r in self.conn.execute(
            "SELECT label, description, value, char_limit FROM memory_blocks ORDER BY label")]

    def replace_memory_block(self, label: str, value: str) -> dict:
        memory.ensure_blocks(self.conn)
        row = self.conn.execute("SELECT char_limit FROM memory_blocks WHERE label = ?", (label,)).fetchone()
        if row is None:
            raise KeyError(f"no memory block {label!r}")
        value = value.strip()
        if len(value) > row["char_limit"]:
            raise ValueError(f"{label} would be {len(value)}/{row['char_limit']} characters - shorten it")
        self.conn.execute("UPDATE memory_blocks SET value = ? WHERE label = ?", (value, label))
        return {"label": label, "value": value, "char_limit": row["char_limit"]}

    def memory_facts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id, text, importance, created_at, last_accessed FROM memory_facts WHERE active = 1 ORDER BY id DESC")]

    def forget_fact(self, fact_id: int) -> None:
        if not memory.forget(self.conn, fact_id):
            raise KeyError(f"no fact {fact_id}")

    def deactivate_rule(self, rule_id: int) -> None:
        if self.conn.execute("UPDATE rules SET active = 0 WHERE id = ? AND active = 1", (rule_id,)).rowcount != 1:
            raise KeyError(f"no active rule {rule_id}")

    def conversation(self, conversation_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT question, answer, created_at FROM conversation_turns WHERE conversation_id = ? ORDER BY id",
            (conversation_id,))]

    # --------------------------------------------------------------------- observability
    def stats(self) -> dict:
        c = self.conn
        by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM transactions GROUP BY status")}
        by_source = {r["s"] or "none": r["n"] for r in c.execute(
            "SELECT category_source s, COUNT(*) n FROM transactions WHERE status='categorized' GROUP BY s")}
        total = sum(by_status.values()) or 1
        llm = c.execute("SELECT purpose, COUNT(*) calls, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cost_usd) cost,"
                        " SUM(cache_hit) hits, SUM(error IS NOT NULL) errors, AVG(latency_ms) ms FROM llm_calls"
                        " GROUP BY purpose").fetchall()
        return {
            "transactions": sum(by_status.values()),
            "by_status": by_status,
            "categorized_by": by_source,
            "automation_rate": round((by_source.get("rule", 0) + by_source.get("llm", 0)) / total, 3),
            "review_backlog": by_status.get("needs_review", 0),
            "rules": {"user": c.execute("SELECT COUNT(*) FROM rules WHERE active=1 AND source='user'").fetchone()[0],
                      "compiled": c.execute("SELECT COUNT(*) FROM rules WHERE active=1 AND source='compiled'").fetchone()[0]},
            "verified_labels": c.execute("SELECT COUNT(*) FROM labels").fetchone()[0],
            "llm": [dict(r) for r in llm],
            "recent_runs": [dict(r) for r in c.execute(
                "SELECT id, status, stats_json, started_at, finished_at FROM runs ORDER BY started_at DESC LIMIT 5")],
        }


def report_to_dict(r: MonthlyReport) -> dict:
    return {"month": r.month, "facts": r.facts, "narrative": r.narrative.model_dump() if r.narrative else None,
            "attempts": r.attempts, "removed_sentences": r.removed_sentences, "markdown": r.markdown}


def as_dict(obj) -> dict:
    return asdict(obj)
