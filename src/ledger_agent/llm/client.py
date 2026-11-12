"""LLM client: the ONLY module that talks to OpenAI.

Everything a production harness needs around a model call lives here, once:
  - structured outputs (`responses.parse` + Pydantic schema) -> typed, validated results or an error
  - tool-calling steps for the agent loop (Responses API function calls)
  - retries with exponential backoff (SDK `max_retries`) and timeouts
  - content-addressed caching -> re-running a batch is free and deterministic
  - token budget enforcement (`UsageMeter`) -> a runaway loop can't burn money
  - audit log of every call (purpose, model, tokens, latency, cost, error) in `llm_calls`
  - privacy: `store=False` so requests aren't retained for later retrieval by the API

Call sites depend on the `LLMClient` protocol, so tests and evals swap in `FakeLLM`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel

from ledger_agent.config import Settings
from ledger_agent.log import get_logger, run_id_var

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model call failed or produced nothing usable (refusal, incomplete, invalid)."""


class BudgetExceeded(RuntimeError):
    """The run's token budget is spent. Callers stop gracefully and can resume later."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict
    raw_arguments: str = ""


@dataclass
class AgentStep:
    text: str
    tool_calls: list[ToolCall]
    output_items: list[dict]          # append these to the conversation verbatim for the next step
    usage: Usage = field(default_factory=Usage)


class UsageMeter:
    """Thread-safe token accounting for one run, with a hard ceiling."""

    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens
        self.usage = Usage()
        self.calls = 0
        self._lock = threading.Lock()

    def check(self) -> None:
        if self.max_tokens is not None and self.usage.total >= self.max_tokens:
            raise BudgetExceeded(f"token budget exhausted ({self.usage.total}/{self.max_tokens})")

    def add(self, u: Usage) -> None:
        with self._lock:
            self.usage.input_tokens += u.input_tokens
            self.usage.output_tokens += u.output_tokens
            self.calls += 1


class LLMClient(Protocol):
    meter: UsageMeter

    def parse(self, *, purpose: str, instructions: str, input: str, schema: type[T],
              model: Optional[str] = None, effort: Optional[str] = None, cache: bool = True) -> T: ...

    def step(self, *, purpose: str, instructions: str, items: list[dict], tools: list[dict],
             model: Optional[str] = None, effort: Optional[str] = None) -> AgentStep: ...


class OpenAIClient:
    def __init__(self, settings: Settings, conn: sqlite3.Connection | None = None, meter: UsageMeter | None = None):
        from openai import OpenAI  # imported lazily so tests never need network libs configured

        self.settings = settings
        self.client = OpenAI(timeout=settings.llm_timeout_s, max_retries=settings.llm_max_retries)
        self.conn = conn
        self.meter = meter or UsageMeter()

    # ------------------------------------------------------------------ helpers
    def _cost(self, u: Usage) -> float | None:
        s = self.settings
        if s.price_input_per_mtok is None or s.price_output_per_mtok is None:
            return None
        return (u.input_tokens * s.price_input_per_mtok + u.output_tokens * s.price_output_per_mtok) / 1e6

    def _audit(self, purpose: str, model: str, u: Usage, latency_ms: int, cache_hit: bool = False,
               error: str | None = None) -> None:
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT INTO llm_calls (run_id, purpose, model, input_tokens, output_tokens, cost_usd, latency_ms, cache_hit, error)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id_var.get(), purpose, model, u.input_tokens, u.output_tokens, self._cost(u), latency_ms,
             int(cache_hit), error),
        )

    @staticmethod
    def _reasoning(effort: str | None) -> dict[str, Any]:
        return {"reasoning": {"effort": effort}} if effort else {}

    @staticmethod
    def _usage(resp: Any) -> Usage:
        u = getattr(resp, "usage", None)
        return Usage(getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)

    # ------------------------------------------------------------------ structured output
    def parse(self, *, purpose: str, instructions: str, input: str, schema: type[T],
              model: Optional[str] = None, effort: Optional[str] = None, cache: bool = True) -> T:
        model = model or self.settings.model_bulk
        effort = effort if effort is not None else self.settings.reasoning_effort_bulk
        key = hashlib.sha256(json.dumps(
            [model, effort, instructions, input, schema.model_json_schema()], sort_keys=True).encode()).hexdigest()

        use_cache = cache and self.settings.llm_cache and self.conn is not None
        if use_cache:
            row = self.conn.execute("SELECT response_json FROM llm_cache WHERE key = ?", (key,)).fetchone()
            if row:
                self._audit(purpose, model, Usage(), 0, cache_hit=True)
                return schema.model_validate_json(row["response_json"])

        self.meter.check()
        t0 = time.perf_counter()
        try:
            resp = self.client.responses.parse(
                model=model, instructions=instructions, input=input, text_format=schema,
                store=False, **self._reasoning(effort),
            )
        except Exception as e:  # openai.APIError & friends, after the SDK's own retries
            self._audit(purpose, model, Usage(), int((time.perf_counter() - t0) * 1000), error=type(e).__name__)
            log.warning("llm call failed", extra={"purpose": purpose, "error": repr(e)[:300]})
            raise LLMError(f"{purpose}: {type(e).__name__}: {e}") from e

        latency = int((time.perf_counter() - t0) * 1000)
        usage = self._usage(resp)
        self.meter.add(usage)
        parsed = getattr(resp, "output_parsed", None)
        if getattr(resp, "status", "completed") == "incomplete" or parsed is None:
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", None) or "no parsed output (refusal?)"
            self._audit(purpose, model, usage, latency, error=str(reason))
            raise LLMError(f"{purpose}: {reason}")

        self._audit(purpose, model, usage, latency)
        log.info("llm call", extra={"purpose": purpose, "model": model, "in": usage.input_tokens,
                                    "out": usage.output_tokens, "ms": latency})
        if use_cache:
            self.conn.execute("INSERT OR REPLACE INTO llm_cache (key, response_json) VALUES (?, ?)",
                              (key, parsed.model_dump_json()))
        return parsed

    # ------------------------------------------------------------------ agent step (tool calling)
    def step(self, *, purpose: str, instructions: str, items: list[dict], tools: list[dict],
             model: Optional[str] = None, effort: Optional[str] = None) -> AgentStep:
        model = model or self.settings.model_agent
        effort = effort if effort is not None else self.settings.reasoning_effort_agent
        self.meter.check()
        t0 = time.perf_counter()
        try:
            resp = self.client.responses.create(
                model=model, instructions=instructions, input=items, tools=tools,
                store=False,                                   # stateless: we own the history
                include=["reasoning.encrypted_content"],       # so reasoning items can be replayed statelessly
                parallel_tool_calls=True, **self._reasoning(effort),
            )
        except Exception as e:
            self._audit(purpose, model, Usage(), int((time.perf_counter() - t0) * 1000), error=type(e).__name__)
            raise LLMError(f"{purpose}: {type(e).__name__}: {e}") from e

        latency = int((time.perf_counter() - t0) * 1000)
        usage = self._usage(resp)
        self.meter.add(usage)
        self._audit(purpose, model, usage, latency)

        calls = []
        for item in resp.output:
            if getattr(item, "type", None) == "function_call":
                try:
                    args = json.loads(item.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"__invalid_json__": item.arguments}
                calls.append(ToolCall(item.call_id, item.name, args, item.arguments or ""))
        return AgentStep(text=resp.output_text or "", tool_calls=calls,
                         output_items=[i.model_dump(exclude_none=True) for i in resp.output], usage=usage)
