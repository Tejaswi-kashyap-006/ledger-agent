"""HTTP API (FastAPI). Run: `ledger serve` or `uvicorn ledger_agent.api:app`.

- One LedgerService (and SQLite connection) per request: no cross-request transaction interleaving.
- Optional bearer-token auth (LEDGER_API_KEY). This is a single-user app; put it behind TLS if exposed.
- Domain errors map to HTTP codes: ValueError -> 422, KeyError -> 404, RuntimeError -> 503.
- If the web UI has been built into `ledger_agent/static`, it is served from `/` (SPA fallback), so one
  process on one port serves both the app and its API.
"""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Callable, Iterator, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ledger_agent.config import Settings, get_settings
from ledger_agent.log import setup_logging
from ledger_agent.service import LedgerService, as_dict, report_to_dict

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"


class CategoryIn(BaseModel):
    category: str


class RuleIn(BaseModel):
    pattern_type: str = "merchant"
    pattern: str
    category: str
    direction: Optional[str] = None


class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class MemoryIn(BaseModel):
    block: str
    text: str


class BlockIn(BaseModel):
    value: str


def create_app(settings: Settings | None = None,
               service_factory: Callable[[], LedgerService] | None = None,
               static_dir: Path | None = STATIC_DIR) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)
    factory = service_factory or (lambda: LedgerService(settings))
    app = FastAPI(title="Ledger Agent", version="0.1.0")

    def service() -> Iterator[LedgerService]:
        svc = factory()
        try:
            yield svc
        finally:
            svc.close()

    def auth(request: Request) -> None:
        if not settings.api_key:
            return
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(header, f"Bearer {settings.api_key}"):   # constant-time comparison
            raise HTTPException(401, "invalid or missing bearer token")

    @app.exception_handler(ValueError)
    async def _value_error(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def _key_error(_, exc: KeyError):
        return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)

    @app.exception_handler(RuntimeError)
    async def _runtime_error(_, exc: RuntimeError):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/healthz")
    def healthz(svc: LedgerService = Depends(service)):
        svc.conn.execute("SELECT 1")
        return {"status": "ok", "llm": svc.llm is not None}

    deps = [Depends(auth)]

    @app.post("/v1/imports", dependencies=deps)
    async def upload(account: str = Form(...), file: UploadFile = File(...), svc: LedgerService = Depends(service)):
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file too large (max 10 MB)")
        return as_dict(svc.import_file(account, file.filename or "upload.csv", data))

    @app.post("/v1/process", dependencies=deps)
    def process(limit: Optional[int] = None, resume: Optional[str] = None, svc: LedgerService = Depends(service)):
        r = svc.process(run_id=resume, limit=limit)
        return {"run_id": r.run_id, "status": r.status, "tokens": r.tokens, "stats": as_dict(r.stats)}

    @app.get("/v1/review", dependencies=deps)
    def review(limit: int = 50, svc: LedgerService = Depends(service)):
        return svc.review_queue(limit)

    @app.get("/v1/audit", dependencies=deps)
    def audit(n: int = 5, svc: LedgerService = Depends(service)):
        return svc.audit_sample(n)

    @app.post("/v1/transactions/{txn_id}/category", dependencies=deps)
    def categorize(txn_id: int, body: CategoryIn, svc: LedgerService = Depends(service)):
        return as_dict(svc.set_category(txn_id, body.category))

    @app.post("/v1/transactions/{txn_id}/accept", dependencies=deps)
    def accept(txn_id: int, svc: LedgerService = Depends(service)):
        return as_dict(svc.accept(txn_id))

    @app.get("/v1/rules", dependencies=deps)
    def rules(svc: LedgerService = Depends(service)):
        return svc.rules()

    @app.post("/v1/rules", dependencies=deps)
    def new_rule(body: RuleIn, svc: LedgerService = Depends(service)):
        return {"id": svc.add_rule(body.pattern_type, body.pattern, body.category, body.direction)}

    @app.post("/v1/chat", dependencies=deps)
    def chat(body: ChatIn, svc: LedgerService = Depends(service)):
        a = svc.ask(body.message, body.conversation_id)
        return {"answer": a.text, "conversation_id": a.conversation_id, "stop": a.stop, "turns": a.turns,
                "tool_calls": a.tool_calls, "tokens": a.tokens}

    @app.get("/v1/reports/{month}", dependencies=deps)
    def report(month: str, format: str = "json", svc: LedgerService = Depends(service)):
        r = svc.report(month)
        return PlainTextResponse(r.markdown, media_type="text/markdown") if format == "md" else report_to_dict(r)

    @app.get("/v1/subscriptions", dependencies=deps)
    def subscriptions(svc: LedgerService = Depends(service)):
        return [as_dict(s) for s in svc.subscriptions()]

    @app.get("/v1/memory", dependencies=deps)
    def memory_view(svc: LedgerService = Depends(service)):
        return svc.memory_view()

    @app.post("/v1/memory", dependencies=deps)
    def memory_set(body: MemoryIn, svc: LedgerService = Depends(service)):
        return {"result": svc.set_memory(body.block, body.text)}

    @app.get("/v1/stats", dependencies=deps)
    def stats(svc: LedgerService = Depends(service)):
        return svc.stats()

    # ---- read endpoints for the web UI -------------------------------------------------
    @app.get("/v1/categories", dependencies=deps)
    def categories():
        from ledger_agent.categories import CATEGORIES
        return list(CATEGORIES)

    @app.get("/v1/months", dependencies=deps)
    def months(svc: LedgerService = Depends(service)):
        return svc.months()

    @app.get("/v1/accounts", dependencies=deps)
    def accounts(svc: LedgerService = Depends(service)):
        return svc.accounts()

    @app.get("/v1/trend", dependencies=deps)
    def trend(svc: LedgerService = Depends(service)):
        return svc.trend()

    @app.get("/v1/memory/blocks", dependencies=deps)
    def memory_blocks(svc: LedgerService = Depends(service)):
        return svc.memory_blocks()

    @app.put("/v1/memory/blocks/{label}", dependencies=deps)
    def memory_block_put(label: str, body: BlockIn, svc: LedgerService = Depends(service)):
        return svc.replace_memory_block(label, body.value)

    @app.get("/v1/memory/facts", dependencies=deps)
    def memory_facts(svc: LedgerService = Depends(service)):
        return svc.memory_facts()

    @app.delete("/v1/memory/facts/{fact_id}", status_code=204, dependencies=deps)
    def memory_fact_delete(fact_id: int, svc: LedgerService = Depends(service)):
        svc.forget_fact(fact_id)

    @app.delete("/v1/rules/{rule_id}", status_code=204, dependencies=deps)
    def rule_delete(rule_id: int, svc: LedgerService = Depends(service)):
        svc.deactivate_rule(rule_id)

    @app.get("/v1/conversations/{conversation_id}", dependencies=deps)
    def conversation(conversation_id: str, svc: LedgerService = Depends(service)):
        return svc.conversation(conversation_id)

    @app.get("/v1/facts/{month}", dependencies=deps)
    def facts(month: str, svc: LedgerService = Depends(service)):
        from ledger_agent.insights.report import month_facts
        return month_facts(svc.conn, month)          # SQL only: no LLM cost, safe for dashboards

    @app.get("/v1/transactions", dependencies=deps)
    def transactions(q: Optional[str] = None, category: Optional[str] = None, status: Optional[str] = None,
                     month: Optional[str] = None, limit: int = 50, offset: int = 0,
                     svc: LedgerService = Depends(service)):
        where, args = [], []
        if q:
            where.append("(t.merchant LIKE ? OR t.description LIKE ?)")
            args += [f"%{q.upper()}%", f"%{q}%"]
        for col, val in (("t.category", category), ("t.status", status)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if month:
            where.append("substr(t.date,1,7) = ?")
            args.append(month)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = svc.conn.execute(f"SELECT COUNT(*) FROM transactions t{clause}", args).fetchone()[0]
        rows = svc.conn.execute(
            "SELECT t.id, t.date, t.amount_minor, t.merchant, t.description, t.category, t.category_source,"
            f" t.confidence, t.status, t.review_reason, a.name AS account FROM transactions t"
            f" JOIN accounts a ON a.id = t.account_id{clause} ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?",
            (*args, max(1, min(limit, 500)), max(0, offset))).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    # ---- the web UI (built by `npm run build` in ui/ into ledger_agent/static) -----------------
    if static_dir is not None and (static_dir / "index.html").is_file():
        root = static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def web_ui(path: str):
            if path.startswith(("v1/", "healthz")):
                raise HTTPException(404, "not found")
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                # hashed build assets never change; index.html must always be revalidated
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})   # SPA routes

    return app


def __getattr__(name: str):
    # `uvicorn ledger_agent.api:app` - build lazily so importing this module has no side effects
    if name == "app":
        return create_app()
    raise AttributeError(name)
