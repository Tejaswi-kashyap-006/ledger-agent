"""Command line interface: `ledger <command>`. Run `ledger -h` for help."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from ledger_agent.categories import CATEGORIES
from ledger_agent.config import get_settings
from ledger_agent.ingest.normalize import format_money
from ledger_agent.log import setup_logging
from ledger_agent.service import LedgerService, as_dict

console = Console()


def _svc() -> LedgerService:
    return LedgerService(get_settings())


def cmd_import(a: argparse.Namespace) -> None:
    svc = _svc()
    for path in a.files:
        p = Path(path)
        r = svc.import_file(a.account, p.name, p.read_bytes())
        color = "green" if r.balance_check in ("ok", "no_balance_column") else "yellow"
        console.print(f"[bold]{p.name}[/] -> {r.account} ({r.profile_name} profile): {r.rows_new} new, "
                      f"{r.rows_duplicate} duplicates, {r.rows_rejected} rejected; balance [{color}]{r.balance_check}[/]")
        for i, why in r.rejects[:5]:
            console.print(f"  [dim]rejected row {i}: {why}[/]")


def cmd_process(a: argparse.Namespace) -> None:
    svc = _svc()
    if svc.llm is None:
        console.print("[yellow]OPENAI_API_KEY not set: only rules will be applied; the rest goes to review.[/]")
    r = svc.process(run_id=a.resume, limit=a.limit)
    s = r.stats
    console.print(f"run [bold]{r.run_id}[/] {r.status}: {s.processed} processed | rules {s.by_rule} | "
                  f"model {s.by_llm} | review {s.to_review} (suspicious {s.suspicious}, direction flags "
                  f"{s.direction_flags}, llm errors {s.llm_errors}) | {r.tokens:,} tokens")
    if r.status == "paused_budget":
        console.print(f"[yellow]Budget exhausted. Resume with: ledger process --resume {r.run_id}[/]")


def _pick_category(text: str) -> str | None:
    text = text.strip().lower()
    if text.isdigit() and 1 <= int(text) <= len(CATEGORIES):
        return CATEGORIES[int(text) - 1]
    hits = [c for c in CATEGORIES if text in c.lower()]
    return hits[0] if len(hits) == 1 else None


def cmd_review(a: argparse.Namespace) -> None:
    svc = _svc()
    audit = a.cmd == "audit"
    items = svc.audit_sample(a.n) if audit else svc.review_queue(a.limit)
    if not items:
        console.print("[green]Nothing to audit.[/]" if audit else "[green]Review queue is empty.[/]")
        return
    if audit:
        console.print("[bold]Audit:[/] spot-check answers the model was CONFIDENT about (one per merchant).")
    cats = Table(show_header=False, box=None)
    for i in range(0, len(CATEGORIES), 3):
        cats.add_row(*[f"[dim]{j + 1:>2}[/] {CATEGORIES[j]}" for j in range(i, min(i + 3, len(CATEGORIES)))])
    console.print(cats)
    console.print("[dim]Enter = accept suggestion · number or text = choose category · s = skip · q = quit[/]\n")
    done = 0
    for it in items:
        status = svc.conn.execute("SELECT status FROM transactions WHERE id=?", (it["id"],)).fetchone()["status"]
        if not audit and status != "needs_review":
            continue  # already fixed by a rule propagated from an earlier answer
        sug = f"{it['suggestion']} ({it['confidence']:.2f})" if it["suggestion"] else "-"
        console.print(f"[bold]#{it['id']}[/] {it['date']} {format_money(it['amount_minor'])} [cyan]{it['merchant']}[/]\n"
                      f"  {it['description']}\n  suggestion: {sug} · reason: {it['review_reason']}"
                      + (f" · model: {it['llm_reason']}" if it["llm_reason"] else ""))
        while True:
            ans = console.input("  category> ").strip()
            if ans.lower() == "q":
                console.print(f"{done} reviewed.")
                return
            if ans.lower() == "s":
                break
            try:
                if ans == "" and it["suggestion"]:
                    r = svc.accept(it["id"])
                else:
                    cat = _pick_category(ans)
                    if cat is None:
                        console.print("  [red]ambiguous or unknown category - try a number[/]")
                        continue
                    r = svc.set_category(it["id"], cat)
            except ValueError as e:
                console.print(f"  [red]{e}[/]")
                continue
            done += 1
            extra = f" · compiled rule #{r.rule_created}, auto-fixed {r.propagated} more" if r.rule_created else ""
            console.print(f"  [green]✓ {r.category}[/]{extra}")
            break
    console.print(f"{done} reviewed.")


def cmd_ask(a: argparse.Namespace) -> None:
    svc = _svc()
    conv = a.conversation
    questions = [a.question] if a.question else None
    while True:
        q = questions.pop(0) if questions else console.input("[bold]you>[/] ").strip()
        if not q or q in ("exit", "quit"):
            return
        ans = svc.ask(q, conv)
        conv = ans.conversation_id
        console.print(Markdown(ans.text))
        console.print(f"[dim]({ans.stop}, {ans.turns} steps, tools: {[c['name'] for c in ans.tool_calls]}, "
                      f"{ans.tokens:,} tokens, conversation {conv})[/]")
        if a.question:
            return


def cmd_report(a: argparse.Namespace) -> None:
    r = _svc().report(a.month)
    if a.out:
        Path(a.out).write_text(r.markdown, encoding="utf-8")
        console.print(f"wrote {a.out}")
    else:
        console.print(Markdown(r.markdown))
    if r.removed_sentences:
        console.print(f"[yellow]verifier removed {len(r.removed_sentences)} sentence(s) with unverifiable numbers[/]")


def cmd_rules(a: argparse.Namespace) -> None:
    svc = _svc()
    if a.add:
        pattern, _, category = a.add.partition("=")
        rule_id = svc.add_rule(a.type, pattern, category, a.direction)
        console.print(f"added rule #{rule_id}")
    t = Table("id", "type", "pattern", "dir", "category", "source", "hits")
    for r in svc.rules():
        t.add_row(str(r["id"]), r["pattern_type"], r["pattern"], r["direction"] or "", r["category"], r["source"],
                  str(r["hits"]))
    console.print(t)


def cmd_subs(a: argparse.Namespace) -> None:
    t = Table("merchant", "cadence", "last", "monthly", "change", "next")
    for s in _svc().subscriptions():
        change = f"[red]{s.price_change_pct:+.1f}%[/]" if s.price_change_pct > 5 else f"{s.price_change_pct:+.1f}%"
        t.add_row(s.merchant, s.cadence, format_money(s.last_amount_minor), format_money(s.monthly_cost_minor),
                  change, s.next_expected)
    console.print(t)


def cmd_memory(a: argparse.Namespace) -> None:
    svc = _svc()
    if a.set:
        block, _, text = a.set.partition("=")
        console.print(svc.set_memory(block.strip(), text.strip()))
    view = svc.memory_view()
    console.print(view["blocks"])
    for f in view["facts"]:
        console.print(f"  fact #{f['id']} (imp {f['importance']:g}): {f['text']}")


def cmd_stats(a: argparse.Namespace) -> None:
    console.print_json(json.dumps(_svc().stats(), default=str))


def cmd_demo(a: argparse.Namespace) -> None:
    from ledger_agent.datagen import HOUSEHOLD_MEMORY, generate

    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    ds = generate(seed=a.seed)
    for name, data in ds.files.items():
        (out / name).write_bytes(data)
    (out / "household_memory.txt").write_text(HOUSEHOLD_MEMORY, encoding="utf-8")
    console.print(f"wrote {len(ds.files)} statements to {out}/ (+ household_memory.txt). Try:\n"
                  f'  ledger memory --set "household={HOUSEHOLD_MEMORY.splitlines()[0]}"\n'
                  f'  ledger import {out}/hdfc_savings_2026-06.csv --account "HDFC Savings"\n'
                  f'  ledger import {out}/icici_card_2026-06.csv --account "ICICI Credit Card"\n'
                  f"  ledger process && ledger review && ledger report 2026-06")


def cmd_serve(a: argparse.Namespace) -> None:
    import uvicorn

    from ledger_agent.api import create_app

    uvicorn.run(create_app(), host=a.host, port=a.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledger", description="AI bookkeeper for bank statements")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="import statement CSV files")
    s.add_argument("files", nargs="+")
    s.add_argument("--account", required=True)
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("process", help="categorize pending transactions")
    s.add_argument("--resume", help="resume a paused run id")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_process)

    s = sub.add_parser("review", help="work through the human review queue")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("audit", help="spot-check confident model answers (catches silent errors)")
    s.add_argument("--n", type=int, default=5)
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("ask", help="ask a question (omit it for an interactive chat)")
    s.add_argument("question", nargs="?")
    s.add_argument("--conversation")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("report", help="monthly report, e.g. 2026-08")
    s.add_argument("month")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("rules", help="list rules, or add one: --add 'ZOMATO=Food:Delivery'")
    s.add_argument("--add")
    s.add_argument("--type", default="merchant", choices=["merchant", "contains", "regex"])
    s.add_argument("--direction", choices=["debit", "credit"])
    s.set_defaults(fn=cmd_rules)

    sub.add_parser("subs", help="recurring payments & price changes").set_defaults(fn=cmd_subs)

    s = sub.add_parser("memory", help="show memory, or set a block: --set 'household=...'")
    s.add_argument("--set")
    s.set_defaults(fn=cmd_memory)

    sub.add_parser("stats", help="automation rate, backlog, LLM usage").set_defaults(fn=cmd_stats)

    s = sub.add_parser("demo", help="write realistic sample statements to a folder")
    s.add_argument("--dir", default="sample_data")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # ₹ on Windows consoles
    settings = get_settings()
    setup_logging(settings.log_level if settings.log_level != "INFO" else "WARNING", settings.log_format)
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except (ValueError, KeyError, RuntimeError, FileNotFoundError) as e:
        console.print(f"[red]error:[/] {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "as_dict"]
