"""Configuration: every knob in one typed place, loaded from env vars / .env (prefix LEDGER_).

Why typed settings: a mistyped threshold ("0,8") should fail at startup, not at 2am inside a batch.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGER_", env_file=".env", extra="ignore")

    # --- storage -------------------------------------------------------------------------
    db_path: Path = Path("data/ledger.db")

    # --- LLM (OpenAI) ----------------------------------------------------------------------
    # OPENAI_API_KEY / OPENAI_BASE_URL are read by the OpenAI SDK itself (no prefix).
    model_bulk: str = "gpt-5.4-mini"          # high-volume, structured work (categorization, import mapping)
    model_agent: str = "gpt-5.4"              # interactive Q&A agent and report writing
    reasoning_effort_bulk: Optional[Literal["none", "minimal", "low", "medium", "high"]] = "low"
    reasoning_effort_agent: Optional[Literal["none", "minimal", "low", "medium", "high"]] = "medium"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 4                  # SDK retries 429/5xx/connection errors with exponential backoff
    llm_cache: bool = True                    # content-addressed cache: re-running a batch costs nothing
    # Prices are NOT hardcoded (they change). Set them from the provider's pricing page to get $ tracking.
    price_input_per_mtok: Optional[float] = None
    price_output_per_mtok: Optional[float] = None

    # --- categorization pipeline ---------------------------------------------------------
    batch_size: int = Field(20, ge=1, le=100)
    auto_accept_confidence: float = Field(0.80, ge=0, le=1)   # below this -> human review queue
    few_shot_examples: int = Field(12, ge=0, le=50)
    rule_min_consistent_corrections: int = Field(2, ge=1)     # corrections needed to compile a rule
    max_tokens_per_run: int = 400_000                         # hard budget per processing run

    # --- agent -----------------------------------------------------------------------------
    agent_max_turns: int = 12
    agent_max_tokens_per_question: int = 120_000
    tool_output_max_chars: int = 6000
    sql_row_limit: int = 200
    sql_timeout_ms: int = 2000
    history_turns: int = 6                                    # past Q/A pairs replayed into context

    # --- privacy -----------------------------------------------------------------------------
    redact_pii: bool = True

    # --- API -----------------------------------------------------------------------------------
    api_key: Optional[str] = None             # if set, required as `Authorization: Bearer <key>`
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"
    currency: str = "INR"


@lru_cache
def get_settings() -> Settings:
    return Settings()
