"""OpenAIClient behaviour with the SDK mocked out: caching, budgets, audit log, errors, tool-call parsing."""

from types import SimpleNamespace

import pytest
from openai.types.responses import ResponseFunctionToolCall

from ledger_agent.categorize.llm_categorizer import CategorizationBatch
from ledger_agent.llm.client import BudgetExceeded, LLMError, OpenAIClient, UsageMeter


class FakeResponses:
    def __init__(self, parse_result=None, create_result=None, error=None):
        self.parse_result, self.create_result, self.error = parse_result, create_result, error
        self.parse_kwargs, self.create_kwargs = [], []

    def parse(self, **kw):
        self.parse_kwargs.append(kw)
        if self.error:
            raise self.error
        return self.parse_result

    def create(self, **kw):
        self.create_kwargs.append(kw)
        return self.create_result


BATCH = CategorizationBatch.model_validate({"items": [{"idx": 0, "category": "Food:Delivery", "confidence": 0.9,
                                                       "reason": "swiggy"}]})


def make(conn, settings, monkeypatch, **fake):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    c = OpenAIClient(settings, conn)
    c.client = SimpleNamespace(responses=FakeResponses(**fake))
    return c


def ok_parse():
    return SimpleNamespace(output_parsed=BATCH, status="completed", incomplete_details=None,
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


def test_parse_audits_and_caches(conn, settings, monkeypatch):
    c = make(conn, settings, monkeypatch, parse_result=ok_parse())
    kw = dict(purpose="categorize", instructions="i", input="x", schema=CategorizationBatch)
    assert c.parse(**kw) == BATCH
    assert c.parse(**kw) == BATCH                                     # served from cache
    fake = c.client.responses
    assert len(fake.parse_kwargs) == 1
    assert fake.parse_kwargs[0]["store"] is False and fake.parse_kwargs[0]["reasoning"] == {"effort": "low"}
    rows = conn.execute("SELECT cache_hit, input_tokens FROM llm_calls ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(0, 1000), (1, 0)]
    assert c.meter.usage.total == 1200


def test_cost_tracked_only_when_prices_configured(conn, settings, monkeypatch):
    settings.price_input_per_mtok, settings.price_output_per_mtok = 1.0, 4.0
    c = make(conn, settings, monkeypatch, parse_result=ok_parse())
    c.parse(purpose="p", instructions="i", input="x", schema=CategorizationBatch, cache=False)
    assert conn.execute("SELECT cost_usd FROM llm_calls").fetchone()[0] == pytest.approx((1000 * 1 + 200 * 4) / 1e6)


def test_budget_blocks_before_calling(conn, settings, monkeypatch):
    c = make(conn, settings, monkeypatch, parse_result=ok_parse())
    c.meter = UsageMeter(max_tokens=1000)
    c.parse(purpose="p", instructions="i", input="a", schema=CategorizationBatch)
    with pytest.raises(BudgetExceeded):
        c.parse(purpose="p", instructions="i", input="b", schema=CategorizationBatch)
    assert len(c.client.responses.parse_kwargs) == 1


def test_sdk_errors_become_llm_errors_and_are_audited(conn, settings, monkeypatch):
    c = make(conn, settings, monkeypatch, error=TimeoutError("slow"))
    with pytest.raises(LLMError, match="TimeoutError"):
        c.parse(purpose="p", instructions="i", input="x", schema=CategorizationBatch)
    assert conn.execute("SELECT error FROM llm_calls").fetchone()[0] == "TimeoutError"


def test_refusal_or_incomplete_is_an_error(conn, settings, monkeypatch):
    bad = SimpleNamespace(output_parsed=None, status="incomplete",
                          incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                          usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    c = make(conn, settings, monkeypatch, parse_result=bad)
    with pytest.raises(LLMError, match="max_output_tokens"):
        c.parse(purpose="p", instructions="i", input="x", schema=CategorizationBatch)


def test_step_parses_function_calls(conn, settings, monkeypatch):
    items = [ResponseFunctionToolCall(type="function_call", call_id="c1", name="run_sql", id="fc_1",
                                      arguments='{"query": "SELECT 1"}', status="completed"),
             ResponseFunctionToolCall(type="function_call", call_id="c2", name="remember", id="fc_2",
                                      arguments='{"fact": broken', status="completed")]
    resp = SimpleNamespace(output=items, output_text="", usage=SimpleNamespace(input_tokens=50, output_tokens=10))
    c = make(conn, settings, monkeypatch, create_result=resp)
    step = c.step(purpose="agent", instructions="sys", items=[{"role": "user", "content": "hi"}], tools=[])
    assert [(t.call_id, t.name, t.arguments) for t in step.tool_calls][0] == ("c1", "run_sql", {"query": "SELECT 1"})
    assert "__invalid_json__" in step.tool_calls[1].arguments
    assert step.output_items[0]["type"] == "function_call" and "status" in step.output_items[0]
    kw = c.client.responses.create_kwargs[0]
    assert kw["store"] is False and kw["include"] == ["reasoning.encrypted_content"]
    assert kw["model"] == settings.model_agent
