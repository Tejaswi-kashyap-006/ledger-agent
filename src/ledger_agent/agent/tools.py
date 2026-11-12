"""The agent's tools: strict JSON-schema function definitions + handlers.

Tool design choices (from "Writing effective tools for agents"):
  - few, high-level tools that match how a person asks questions (spending_summary) PLUS one
    general escape hatch (run_sql) guarded by the SQL sandbox
  - strict schemas (`strict: true`, all params required, nullable where optional) -> arguments
    always parse; enums for categories/blocks so the model can't invent values
  - outputs are compact text tables with amounts formatted like a human would read them
  - errors are actionable ("use YYYY-MM-DD"), returned as tool output so the model can recover
  - write access is minimal: memory updates (things the user said) and *proposals* for
    recategorization that land in the human review queue - the agent cannot rewrite the ledger
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from ledger_agent import memory
from ledger_agent.agent.sql_guard import SQLRejected, run_readonly
from ledger_agent.categories import CATEGORIES, NON_EXPENSE
from ledger_agent.config import Settings
from ledger_agent.ingest.normalize import format_money
from ledger_agent.insights.recurring import detect_recurring


@dataclass
class ToolContext:
    conn: sqlite3.Connection
    settings: Settings


class ToolError(ValueError):
    """Raised by handlers for invalid input; the message is shown to the model."""


def _date(s: str | None, field: str) -> str | None:
    if s is None:
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError as e:
        raise ToolError(f"{field} must be YYYY-MM-DD, got {s!r}") from e


def _nullable(t: str | dict) -> dict:
    base = {"type": t} if isinstance(t, str) else t
    if "enum" in base:
        return {**base, "type": [base.get("type", "string"), "null"], "enum": [*base["enum"], None]}
    return {**base, "type": [base["type"], "null"]}


def _fn(name: str, description: str, props: dict) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}


# ------------------------------------------------------------------------------------------ handlers
def spending_summary(ctx: ToolContext, start_date: str, end_date: str, group_by: str, direction: str) -> str:
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    key = {"category": "COALESCE(category,'Uncategorized')", "merchant": "merchant", "month": "substr(date,1,7)"}[group_by]
    sign = "< 0" if direction == "debit" else "> 0"
    rows = ctx.conn.execute(
        f"SELECT {key} AS k, SUM(ABS(amount_minor)) AS total, COUNT(*) AS n FROM transactions "
        f"WHERE date BETWEEN ? AND ? AND amount_minor {sign} GROUP BY k ORDER BY total DESC LIMIT 40",
        (start, end)).fetchall()
    if not rows:
        return f"No {direction} transactions between {start} and {end}."
    grand = sum(r["total"] for r in rows)
    excluded = sum(r["total"] for r in rows if group_by == "category" and r["k"] in NON_EXPENSE)
    lines = [f"{direction} {start}..{end} grouped by {group_by}:", "group | total | count"]
    lines += [f"{r['k'] or '(unknown)'} | {format_money(r['total'])} | {r['n']}" for r in rows]
    lines.append(f"TOTAL | {format_money(grand)} | {sum(r['n'] for r in rows)}")
    if excluded:
        lines.append(f"(of which transfers-to-self/investments, usually not 'spending': {format_money(excluded)})")
    return "\n".join(lines)


def search_transactions(ctx: ToolContext, text: str | None, category: str | None, start_date: str | None,
                        end_date: str | None, min_amount: float | None, limit: int) -> str:
    where, args = [], []
    if text:
        where.append("(merchant LIKE ? OR description LIKE ?)")
        args += [f"%{text.upper()}%", f"%{text}%"]
    if category:
        where.append("category = ?")
        args.append(category)
    if start_date:
        where.append("date >= ?")
        args.append(_date(start_date, "start_date"))
    if end_date:
        where.append("date <= ?")
        args.append(_date(end_date, "end_date"))
    if min_amount is not None:
        where.append("ABS(amount_minor) >= ?")
        args.append(int(min_amount * 100))
    limit = max(1, min(int(limit), 50))
    sql = ("SELECT id, date, amount_minor, merchant, COALESCE(category,'Uncategorized') c, status, description "
           "FROM transactions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY date DESC LIMIT ?")
    rows = ctx.conn.execute(sql, (*args, limit)).fetchall()
    if not rows:
        return "No matching transactions."
    out = ["id | date | amount | merchant | category | status | description"]
    out += [f"{r['id']} | {r['date']} | {format_money(r['amount_minor'])} | {r['merchant']} | {r['c']} | {r['status']} | "
            f"{r['description'][:60]}" for r in rows]
    return "\n".join(out)


def run_sql(ctx: ToolContext, query: str) -> str:
    try:
        return run_readonly(ctx.conn, query, ctx.settings.sql_row_limit, ctx.settings.sql_timeout_ms)\
            .to_text(ctx.settings.tool_output_max_chars)
    except SQLRejected as e:
        raise ToolError(str(e)) from e


def recurring_payments(ctx: ToolContext) -> str:
    subs = detect_recurring(ctx.conn)
    if not subs:
        return "No recurring payments detected (need at least 3 regular, similar charges)."
    out = ["merchant | category | cadence | last amount | monthly cost | price change | next expected"]
    out += [f"{s.merchant} | {s.category} | {s.cadence} | {format_money(-s.last_amount_minor)} | "
            f"{format_money(-s.monthly_cost_minor)} | {s.price_change_pct:+.1f}% | {s.next_expected}" for s in subs]
    return "\n".join(out)


def memory_update(ctx: ToolContext, block: str, old: str, new: str) -> str:
    try:
        return memory.update_block(ctx.conn, block, old, new)
    except ValueError as e:
        raise ToolError(str(e)) from e


def remember(ctx: ToolContext, fact: str, importance: int) -> str:
    return f"remembered fact #{memory.remember(ctx.conn, fact, importance)}"


def propose_recategorization(ctx: ToolContext, transaction_ids: list[int], category: str, reason: str) -> str:
    if category not in CATEGORIES:
        raise ToolError(f"unknown category {category!r}")
    ids = [int(i) for i in transaction_ids][:50]
    if not ids:
        raise ToolError("transaction_ids is empty")
    q = ",".join("?" * len(ids))
    n = ctx.conn.execute(
        f"UPDATE transactions SET status='needs_review', category=?, category_source='llm', review_reason='agent_proposal',"
        f" llm_reason=?, updated_at=datetime('now') WHERE id IN ({q}) AND category_source != 'user'",
        (category, reason[:200], *ids)).rowcount
    return (f"Queued {n} transaction(s) for the user's review with suggestion {category!r}. "
            f"(User-verified transactions are never changed by proposals.) Tell the user to run `ledger review`.")


# ------------------------------------------------------------------------------------------ registry
_CAT_ENUM = {"type": "string", "enum": list(CATEGORIES)}

TOOLS: dict[str, tuple[dict, Callable[..., str]]] = {
    "spending_summary": (_fn(
        "spending_summary",
        "Totals of money out (debit) or in (credit) between two dates, grouped by category, merchant or month. "
        "Prefer this for 'how much did I spend on X' questions. Dates are inclusive, YYYY-MM-DD.",
        {"start_date": {"type": "string"}, "end_date": {"type": "string"},
         "group_by": {"type": "string", "enum": ["category", "merchant", "month"]},
         "direction": {"type": "string", "enum": ["debit", "credit"]}}), spending_summary),
    "search_transactions": (_fn(
        "search_transactions",
        "Find individual transactions by merchant/description text, category, date range or minimum amount (rupees). "
        "Use null for filters you don't need. Returns ids you can cite or propose recategorizations for.",
        {"text": _nullable("string"), "category": _nullable(_CAT_ENUM), "start_date": _nullable("string"),
         "end_date": _nullable("string"), "min_amount": _nullable("number"), "limit": {"type": "integer"}}),
        search_transactions),
    "run_sql": (_fn(
        "run_sql",
        "Run ONE read-only SQLite SELECT for questions the other tools can't answer. The only table is "
        "v_transactions(id, date 'YYYY-MM-DD', month 'YYYY-MM', amount REAL (negative = money out), "
        "direction 'debit'|'credit', abs_amount REAL, merchant, channel, category, status, account, description). "
        "Aggregate in SQL (SUM, GROUP BY); results are capped at 200 rows.",
        {"query": {"type": "string"}}), run_sql),
    "recurring_payments": (_fn(
        "recurring_payments",
        "Detected subscriptions/EMIs/rent: cadence, monthly cost, price changes and next expected date.", {}),
        recurring_payments),
    "memory_update": (_fn(
        "memory_update",
        "Edit the user's pinned memory when they tell you something durable (who their landlord is, a budget goal, "
        "a preference). old='' appends a line; otherwise replaces old with new. Never store secrets.",
        {"block": {"type": "string", "enum": ["household", "preferences", "goals"]},
         "old": {"type": "string"}, "new": {"type": "string"}}), memory_update),
    "remember": (_fn(
        "remember",
        "Save a smaller long-term fact the user told you (importance 1-10). Retrieved automatically when relevant.",
        {"fact": {"type": "string"}, "importance": {"type": "integer"}}), remember),
    "propose_recategorization": (_fn(
        "propose_recategorization",
        "Suggest a new category for transactions (by id). This does NOT change the ledger: it queues the "
        "suggestion for the user's review.",
        {"transaction_ids": {"type": "array", "items": {"type": "integer"}}, "category": _CAT_ENUM,
         "reason": {"type": "string"}}), propose_recategorization),
}


def tool_specs() -> list[dict]:
    return [spec for spec, _ in TOOLS.values()]


def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool; return (output, is_error). Never raises - errors are observations for the model."""
    if name not in TOOLS:
        return f"Unknown tool {name!r}. Available: {', '.join(TOOLS)}", True
    if "__invalid_json__" in args:
        return "Your arguments were not valid JSON. Call the tool again with valid JSON arguments.", True
    _, handler = TOOLS[name]
    try:
        out = handler(ctx, **args)
    except ToolError as e:
        return f"Error: {e}", True
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}", True
    except sqlite3.Error as e:
        return f"Error: database error in {name}: {e}", True
    limit = ctx.settings.tool_output_max_chars
    if len(out) > limit:
        out = out[:limit] + f"\n[... truncated {len(out) - limit} chars; narrow the date range or filters ...]"
    return out, False

