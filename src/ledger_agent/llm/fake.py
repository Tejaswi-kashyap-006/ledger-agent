"""Deterministic stand-ins for the LLM, used by tests, CI and `--fake` evals.

`FakeLLM` implements the same protocol as `OpenAIClient`, so the whole pipeline (batching,
checkpoints, review routing, rule compilation, agent loop) runs offline and reproducibly.
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any, Callable, Optional

from pydantic import BaseModel

from ledger_agent.llm.client import AgentStep, LLMError, ToolCall, Usage, UsageMeter

ParseHandler = Callable[[str, str, str, type], Any]   # (purpose, instructions, input, schema) -> model|dict
_ids = itertools.count(1)


def tool_step(*calls: tuple[str, dict], text: str = "") -> AgentStep:
    tcs = [ToolCall(f"call_{next(_ids)}", n, a, json.dumps(a)) for n, a in calls]
    items = [{"type": "function_call", "call_id": c.call_id, "name": c.name, "arguments": c.raw_arguments} for c in tcs]
    return AgentStep(text=text, tool_calls=tcs, output_items=items, usage=Usage(50, 10))


def answer_step(text: str) -> AgentStep:
    item = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
    return AgentStep(text=text, tool_calls=[], output_items=[item], usage=Usage(50, 10))


class FakeLLM:
    def __init__(self, parse_handler: ParseHandler | None = None, steps: list[AgentStep | Callable] | None = None,
                 meter: UsageMeter | None = None):
        self.parse_handler = parse_handler
        self.steps = list(steps or [])
        self.meter = meter or UsageMeter()
        self.parse_calls: list[dict] = []
        self.step_calls: list[dict] = []

    def parse(self, *, purpose: str, instructions: str, input: str, schema: type, model: Optional[str] = None,
              effort: Optional[str] = None, cache: bool = True):
        self.meter.check()
        self.parse_calls.append({"purpose": purpose, "instructions": instructions, "input": input})
        if self.parse_handler is None:
            raise LLMError("FakeLLM has no parse_handler")
        out = self.parse_handler(purpose, instructions, input, schema)
        self.meter.add(Usage(len(input) // 4, 50))
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, BaseModel) else schema.model_validate(out)

    def step(self, *, purpose: str, instructions: str, items: list[dict], tools: list[dict],
             model: Optional[str] = None, effort: Optional[str] = None) -> AgentStep:
        self.meter.check()
        self.step_calls.append({"purpose": purpose, "instructions": instructions,
                                "items": json.loads(json.dumps(items, default=str)), "tools": tools})
        if not self.steps:
            raise AssertionError("FakeLLM ran out of scripted agent steps")
        s = self.steps.pop(0)
        s = s(items) if callable(s) else s
        self.meter.add(s.usage)
        return s


# --------------------------------------------------------------------------------------------
# A keyword "model" for offline evals: a deliberately mediocre baseline, so the eval harness,
# review routing and the learning loop can be exercised without spending tokens.
# --------------------------------------------------------------------------------------------
KEYWORDS = [
    (r"SALARY|PAYROLL", "Income:Salary", 0.95),
    (r"INTEREST|SB INT", "Income:Interest & Dividends", 0.9),
    (r"REFUND|CASHBACK|REVERSAL", "Income:Refund & Cashback", 0.85),
    (r"SWIGGY|ZOMATO", "Food:Delivery", 0.9),
    (r"BIGBASKET|BLINKIT|ZEPTO|DMART|GROCER", "Food:Groceries", 0.85),
    (r"STARBUCKS|CAFE|RESTAURANT|DOMINOS|MCDONALD", "Food:Dining Out", 0.8),
    (r"UBER|OLA|RAPIDO", "Transport:Cab & Auto", 0.9),
    (r"PETROL|FUEL|HPCL|BPCL|INDIAN OIL|IOCL", "Transport:Fuel", 0.85),
    (r"METRO|IRCTC", "Transport:Public Transit", 0.7),
    (r"AMAZON|FLIPKART|MYNTRA|MEESHO", "Shopping:Online", 0.75),
    (r"NETFLIX|SPOTIFY|HOTSTAR|PRIME|YOUTUBE", "Entertainment:Subscriptions", 0.9),
    (r"AIRTEL|JIO|VODAFONE|\bVI\b|ACT FIBERNET|BROADBAND", "Bills:Mobile & Internet", 0.85),
    (r"BESCOM|ELECTRICITY|BWSSB|WATER", "Bills:Electricity & Water", 0.85),
    (r"APOLLO|PHARM|MEDPLUS|1MG", "Health:Pharmacy", 0.8),
    (r"CULT|GYM", "Health:Fitness", 0.8),
    (r"ZERODHA|GROWW|MUTUAL|SIP|NPS", "Investments", 0.85),
    (r"LIC|INSURANCE|POLICYBAZAAR", "Insurance", 0.8),
    (r"EMI|BAJAJ FINANCE|LOAN", "Loans & EMI", 0.8),
    (r"\bATM\b", "Cash Withdrawal", 0.95),
    (r"CHARGES|CHRG|FEE", "Fees & Bank Charges", 0.85),
    (r"MAKEMYTRIP|INDIGO|GOIBIBO", "Travel:Flights & Trains", 0.8),
    (r"RENT", "Housing:Rent", 0.7),
]


def keyword_parse_handler(purpose: str, instructions: str, input: str, schema: type) -> Any:
    """Handles 'categorize' requests by keyword matching over the JSON the pipeline sends."""
    if purpose != "categorize":
        raise LLMError(f"keyword fake cannot handle purpose {purpose!r}")
    payload = json.loads(input[input.index("<transactions>") + 14: input.index("</transactions>")])
    examples = []
    if "<verified_examples>" in input:
        examples = json.loads(input[input.index("<verified_examples>") + 19: input.index("</verified_examples>")])
    by_merchant = {e["merchant"]: e["category"] for e in examples if e.get("merchant")}
    items = []
    for t in payload:
        text = f"{t['merchant']} {t['description']}".upper()
        cat, conf = ("Transfers:To People", 0.5) if t["direction"] == "debit" else ("Income:Other", 0.4)
        if t["merchant"] in by_merchant:            # imitate in-context learning from verified examples
            items.append({"idx": t["idx"], "category": by_merchant[t["merchant"]], "confidence": 0.95,
                          "reason": "same merchant as a verified example"})
            continue
        for pat, c, cf in KEYWORDS:
            if re.search(pat, text):
                cat, conf = c, cf
                break
        items.append({"idx": t["idx"], "category": cat, "confidence": conf, "reason": "keyword match"})
    return {"items": items}
