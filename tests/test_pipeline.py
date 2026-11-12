import json

from ledger_agent.categorize.llm_categorizer import CategorizationBatch
from ledger_agent.categorize.pipeline import direction_ok, process_pending
from ledger_agent.categorize.rules import add_rule
from ledger_agent.llm.client import LLMError, UsageMeter
from ledger_agent.llm.fake import FakeLLM, keyword_parse_handler


def txns_in(input_text):
    return json.loads(input_text[input_text.index("<transactions>") + 14: input_text.index("</transactions>")])


def const_handler(category, confidence):
    def h(purpose, instructions, input, schema):
        return {"items": [{"idx": t["idx"], "category": category, "confidence": confidence, "reason": "x"}
                          for t in txns_in(input)]}
    return h


def statuses(conn):
    return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM transactions GROUP BY status")}


def test_full_run_with_keyword_model(loaded, settings, keyword_llm, dataset):
    r = process_pending(loaded, keyword_llm, settings)
    assert r.status == "completed" and r.stats.processed == len(dataset.labels)
    assert statuses(loaded).get("pending", 0) == 0
    assert r.stats.suspicious == 1                                   # the injected narration
    row = loaded.execute("SELECT status, review_reason FROM transactions WHERE description LIKE '%IGNORE PREVIOUS%'")\
        .fetchone()
    assert (row["status"], row["review_reason"]) == ("needs_review", "suspicious_text")
    assert r.stats.batches == -(-len(dataset.labels) // settings.batch_size)


def test_rules_run_before_the_model(loaded, settings):
    add_rule(loaded, "merchant", "SWIGGY", "Food:Delivery", source="user")
    llm = FakeLLM(parse_handler=const_handler("Other", 0.9))
    process_pending(loaded, llm, settings)
    sent = [t["merchant"] for c in llm.parse_calls for t in txns_in(c["input"])]
    assert "SWIGGY" not in sent
    n = loaded.execute("SELECT COUNT(*) FROM transactions WHERE merchant='SWIGGY' AND category_source='rule'").fetchone()[0]
    assert n == loaded.execute("SELECT COUNT(*) FROM transactions WHERE merchant='SWIGGY'").fetchone()[0] > 5


def test_low_confidence_goes_to_review(loaded, settings):
    process_pending(loaded, FakeLLM(parse_handler=const_handler("Other", 0.3)), settings)
    row = loaded.execute("SELECT COUNT(*) n FROM transactions WHERE review_reason='low_confidence'").fetchone()
    assert row["n"] > 100


def test_direction_sensor_flags_income_on_debits(loaded, settings):
    process_pending(loaded, FakeLLM(parse_handler=const_handler("Income:Salary", 0.99)), settings)
    flagged = loaded.execute("SELECT COUNT(*) FROM transactions WHERE review_reason='direction_mismatch'").fetchone()[0]
    debits = loaded.execute("SELECT COUNT(*) FROM transactions WHERE amount_minor < 0").fetchone()[0]
    assert flagged == debits
    assert direction_ok("Income:Refund & Cashback", 100) and not direction_ok("Food:Delivery", 100)
    assert direction_ok("Transfers:Self", 100) and direction_ok("Transfers:Self", -100)


def test_llm_failure_degrades_to_review_and_run_continues(loaded, settings):
    calls = {"n": 0}

    def flaky(purpose, instructions, input, schema):
        calls["n"] += 1
        return LLMError("503") if calls["n"] == 1 else const_handler("Other", 0.9)(purpose, instructions, input, schema)

    r = process_pending(loaded, FakeLLM(parse_handler=flaky), settings)
    assert r.status == "completed" and r.stats.llm_errors == 1
    assert loaded.execute("SELECT COUNT(*) FROM transactions WHERE review_reason='llm_no_answer'").fetchone()[0] > 0
    assert statuses(loaded).get("pending", 0) == 0


def test_skipped_items_are_retried_once(loaded, settings):
    def skip_first(purpose, instructions, input, schema):
        items = txns_in(input)
        keep = items[1:] if len(items) > 1 and "call1" not in skip_first.__dict__ else items
        skip_first.__dict__["call1"] = True
        return {"items": [{"idx": t["idx"], "category": "Other", "confidence": 0.9, "reason": "x"} for t in keep]}

    llm = FakeLLM(parse_handler=skip_first)
    process_pending(loaded, llm, settings, limit=5)
    assert len(llm.parse_calls) == 2 and len(txns_in(llm.parse_calls[1]["input"])) == 1
    assert loaded.execute("SELECT COUNT(*) FROM transactions WHERE status='categorized'").fetchone()[0] == 5


def test_budget_pause_and_resume_without_double_work(loaded, settings):
    llm = FakeLLM(parse_handler=const_handler("Other", 0.9), meter=UsageMeter(max_tokens=1))
    llm.meter.usage.input_tokens = 0
    # allow exactly one LLM batch: the meter trips before the 2nd call
    orig_parse = llm.parse

    def parse_then_exhaust(**kw):
        out = orig_parse(**kw)
        llm.meter.usage.input_tokens = 10
        return out

    llm.parse = parse_then_exhaust
    first = process_pending(loaded, llm, settings)
    assert first.status == "paused_budget"
    done_after_pause = loaded.execute("SELECT COUNT(*) FROM transactions WHERE status!='pending'").fetchone()[0]
    assert 0 < done_after_pause < 121
    assert first.stats.processed == done_after_pause                 # stats rolled back with the failed batch

    resumed = process_pending(loaded, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings, run_id=first.run_id)
    assert resumed.run_id == first.run_id and resumed.status == "completed"
    assert resumed.stats.processed == 121 and statuses(loaded).get("pending", 0) == 0


def test_prompt_is_redacted_and_marks_untrusted_data(loaded, settings, keyword_llm):
    process_pending(loaded, keyword_llm, settings)
    call = keyword_llm.parse_calls[0]
    assert "UNTRUSTED DATA" in call["instructions"]
    everything = " ".join(c["input"] for c in keyword_llm.parse_calls)
    assert "ramesh.kumar@" not in everything and "sunita.devi56@" not in everything
    assert not any(len(tok) >= 12 and tok.isdigit() for tok in everything.replace("/", " ").split())


def test_schema_enum_rejects_invented_categories():
    import pydantic
    try:
        CategorizationBatch.model_validate({"items": [{"idx": 0, "category": "Crypto Gains", "confidence": 1,
                                                       "reason": ""}]})
    except pydantic.ValidationError:
        return
    raise AssertionError("invalid category accepted")


def test_keyword_fake_uses_verified_examples(conn):
    out = keyword_parse_handler("categorize", "", '<verified_examples>[{"merchant": "TRUFFLES", "category": '
                                '"Food:Dining Out"}]</verified_examples><transactions>[{"idx": 0, "merchant": "TRUFFLES",'
                                ' "description": "TRUFFLES", "direction": "debit"}]</transactions>', CategorizationBatch)
    assert out["items"][0]["category"] == "Food:Dining Out"
