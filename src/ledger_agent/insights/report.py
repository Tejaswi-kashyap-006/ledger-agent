"""Monthly report: numbers from SQL, words from the LLM, and a verifier that keeps them honest.

The failure mode this guards against: an LLM writing "you spent ₹48,200 on food" when the data says
₹42,800. Fluent and wrong is the worst kind of wrong in finance. So:

    facts      = deterministic SQL (the source of truth)
    narrative  = LLM, told to use ONLY numbers from the facts
    verifier   = extract every number from the narrative; each must match a fact value
    on failure = feed the ungrounded numbers back and retry (evaluator-optimizer, code as evaluator);
                 still failing -> drop the offending sentences. Never publish an unverified number.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from pydantic import BaseModel

from ledger_agent.categories import INCOME_PREFIX, NON_EXPENSE
from ledger_agent.config import Settings
from ledger_agent.ingest.normalize import format_money
from ledger_agent.insights.recurring import detect_recurring
from ledger_agent.llm.client import LLMClient, LLMError
from ledger_agent.log import get_logger

log = get_logger("report")


class ReportNarrative(BaseModel):
    headline: str
    highlights: list[str]
    watch_outs: list[str]
    suggestions: list[str]


@dataclass
class MonthlyReport:
    month: str
    facts: dict
    narrative: ReportNarrative | None
    attempts: int = 0
    removed_sentences: list[str] = field(default_factory=list)
    markdown: str = ""


def _prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _rupees(minor: int) -> int:
    return round(minor / 100)


def month_facts(conn: sqlite3.Connection, month: str) -> dict:
    def by_category(mon: str) -> dict[str, int]:
        rows = conn.execute("SELECT COALESCE(category,'Uncategorized') c, SUM(amount_minor) s FROM transactions "
                            "WHERE substr(date,1,7)=? AND amount_minor < 0 GROUP BY c", (mon,)).fetchall()
        return {r["c"]: -r["s"] for r in rows if r["c"] not in NON_EXPENSE}

    income = conn.execute("SELECT COALESCE(SUM(amount_minor),0) s FROM transactions WHERE substr(date,1,7)=? AND "
                          "amount_minor > 0 AND COALESCE(category,'') LIKE ?", (month, INCOME_PREFIX + "%")).fetchone()["s"]
    cats, prev = by_category(month), by_category(_prev_month(month))
    expenses = sum(cats.values())
    top = sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:8]
    merchants = conn.execute("SELECT merchant, -SUM(amount_minor) s, COUNT(*) n FROM transactions WHERE substr(date,1,7)=?"
                             " AND amount_minor < 0 AND merchant != '' GROUP BY merchant ORDER BY s DESC LIMIT 5",
                             (month,)).fetchall()
    changes = []
    for c, amt in top:
        if prev.get(c):
            pct = round((amt - prev[c]) / prev[c] * 100)
            if abs(pct) >= 20 and abs(amt - prev[c]) >= 50000:
                changes.append({"category": c, "this_month": _rupees(amt), "last_month": _rupees(prev[c]),
                                "change_pct": pct})
    pending = conn.execute("SELECT COUNT(*) n FROM transactions WHERE substr(date,1,7)=? AND status != 'categorized'",
                           (month,)).fetchone()["n"]
    subs = [s for s in detect_recurring(conn) if s.last_date[:7] == month]
    return {
        "month": month,
        "income": _rupees(income),
        "expenses": _rupees(expenses),
        "net_savings": _rupees(income - expenses),
        "savings_rate_pct": round((income - expenses) / income * 100) if income else None,
        "top_categories": [{"category": c, "amount": _rupees(a), "share_pct": round(a / expenses * 100) if expenses else 0}
                           for c, a in top],
        "top_merchants": [{"merchant": r["merchant"], "amount": _rupees(r["s"]), "count": r["n"]} for r in merchants],
        "big_changes_vs_last_month": changes,
        "subscriptions": [{"merchant": s.merchant, "cadence": s.cadence, "amount": _rupees(s.last_amount_minor),
                           "price_change_pct": s.price_change_pct} for s in subs],
        "unreviewed_transactions": pending,
    }


# ------------------------------------------------------------------------------ grounding verifier
_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\d])")


def _fact_numbers(obj) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
        out.add(float(abs(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _fact_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _fact_numbers(v)
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            out.add(float(m.replace(",", "")))
    return out


def ungrounded_numbers(text: str, facts: dict) -> list[str]:
    allowed = _fact_numbers(facts)
    bad = []
    for raw in _NUM.findall(text):
        v = float(raw.replace(",", ""))
        if v <= 12 or 2000 <= v <= 2100:           # small counts, month numbers, years
            continue
        if not any(abs(v - a) <= max(1.0, abs(a) * 0.005) for a in allowed):
            bad.append(raw)
    return bad


REPORT_INSTRUCTIONS = """You write a short, warm, specific monthly money report for an Indian household.
Use ONLY the numbers present in <facts>; never compute new totals, averages or percentages yourself.
Write amounts in rupees like ₹12,345. 2-4 highlights, 0-3 watch-outs, 1-3 practical suggestions.
If there are unreviewed transactions, mention that totals may change once they are reviewed."""


def write_report(conn: sqlite3.Connection, llm: LLMClient | None, month: str, settings: Settings,
                 max_attempts: int = 3) -> MonthlyReport:
    facts = month_facts(conn, month)
    report = MonthlyReport(month, facts, None)
    if llm is not None:
        feedback = ""
        for attempt in range(1, max_attempts + 1):
            report.attempts = attempt
            try:
                nar = llm.parse(purpose="report", instructions=REPORT_INSTRUCTIONS, model=settings.model_agent,
                                input=f"<facts>{json.dumps(facts, ensure_ascii=False)}</facts>" + feedback,
                                schema=ReportNarrative, cache=not feedback)
            except LLMError as e:
                log.warning("report narrative failed", extra={"error": str(e)[:200]})
                break
            bad = ungrounded_numbers(" ".join([nar.headline, *nar.highlights, *nar.watch_outs, *nar.suggestions]), facts)
            report.narrative = nar
            if not bad:
                break
            feedback = (f"\n<verifier_feedback>Your previous draft used numbers that are NOT in the facts: {bad}. "
                        "Rewrite using only numbers that appear in <facts>.</verifier_feedback>")
        if report.narrative is not None:
            report.narrative, report.removed_sentences = _strip_ungrounded(report.narrative, facts)
    report.markdown = render_markdown(report)
    return report


def _strip_ungrounded(n: ReportNarrative, facts: dict) -> tuple[ReportNarrative, list[str]]:
    removed: list[str] = []

    def keep(items: list[str]) -> list[str]:
        good = []
        for s in items:
            (removed if ungrounded_numbers(s, facts) else good).append(s)
        return good

    headline = n.headline if not ungrounded_numbers(n.headline, facts) else f"Your money in {facts['month']}"
    return ReportNarrative(headline=headline, highlights=keep(n.highlights), watch_outs=keep(n.watch_outs),
                           suggestions=keep(n.suggestions)), removed


def render_markdown(r: MonthlyReport) -> str:
    f = r.facts
    inr = lambda rupees: format_money(rupees * 100).rsplit(".", 1)[0]  # noqa: E731
    lines = [f"# {r.narrative.headline if r.narrative else 'Monthly report'} ({f['month']})", ""]
    lines += [f"**Income** {inr(f['income'])} · **Expenses** {inr(f['expenses'])} · **Net** {inr(f['net_savings'])}"
              + (f" · **Savings rate** {f['savings_rate_pct']}%" if f["savings_rate_pct"] is not None else ""), ""]
    if r.narrative:
        for title, items in (("Highlights", r.narrative.highlights), ("Watch out", r.narrative.watch_outs),
                             ("Suggestions", r.narrative.suggestions)):
            if items:
                lines += [f"## {title}", *[f"- {s}" for s in items], ""]
    lines += ["## Where the money went", "| Category | Amount | Share |", "|---|---:|---:|"]
    lines += [f"| {c['category']} | {inr(c['amount'])} | {c['share_pct']}% |" for c in f["top_categories"]]
    if f["subscriptions"]:
        lines += ["", "## Recurring payments", "| Merchant | Cadence | Amount | Price change |", "|---|---|---:|---:|"]
        lines += [f"| {s['merchant']} | {s['cadence']} | {inr(s['amount'])} | {s['price_change_pct']:+.1f}% |"
                  for s in f["subscriptions"]]
    if f["unreviewed_transactions"]:
        lines += ["", f"> {f['unreviewed_transactions']} transactions still need review; totals may change."]
    return "\n".join(lines) + "\n"
