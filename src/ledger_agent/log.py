"""Structured logging with a per-run correlation id.

Every log line emitted while processing a run carries `run_id`, so one grep reconstructs
everything that happened in that run - across the pipeline, the LLM client and the tools.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": run_id_var.get(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in vars(record).items() if k not in _RESERVED}
        extra_txt = " ".join(f"{k}={v}" for k, v in extras.items())
        base = f"{time.strftime('%H:%M:%S')} {record.levelname:<7} [{run_id_var.get()}] {record.name}: {record.getMessage()}"
        return f"{base} {extra_txt}".rstrip()


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger("ledger_agent")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ledger_agent.{name}")
