from ledger_agent.categorize.pipeline import process_pending
from ledger_agent.insights.recurring import detect_recurring
from ledger_agent.insights.report import ReportNarrative, month_facts, ungrounded_numbers, write_report
from ledger_agent.llm.fake import FakeLLM, keyword_parse_handler


def test_recurring_detects_subscriptions_and_price_hike(loaded):
    subs = {s.merchant: s for s in detect_recurring(loaded)}
    assert {"NETFLIX COM", "SPOTIFY", "ACT FIBERNET", "RAMESH KUMAR", "ZERODHA BROKING", "BAJAJ FINANCE"} <= set(subs)
    assert subs["NETFLIX COM"].cadence == "monthly" and subs["NETFLIX COM"].price_change_pct == 23.1
    assert subs["SPOTIFY"].price_change_pct == 0.0
    assert "UBER" not in subs                                          # frequent but irregular amounts


def test_month_facts_match_ground_truth(loaded, dataset, settings):
    process_pending(loaded, FakeLLM(parse_handler=keyword_parse_handler), settings)
    # make the ledger match ground truth, then facts must equal a direct computation
    for t in dataset.labels:
        loaded.execute("UPDATE transactions SET category=? WHERE date=? AND amount_minor=? AND description=?",
                       (t.category, t.day.isoformat(), t.amount_minor, t.description))
    f = month_facts(loaded, "2026-07")
    july = [t for t in dataset.labels if t.day.isoformat().startswith("2026-07")]
    income = sum(t.amount_minor for t in july if t.amount_minor > 0 and t.category.startswith("Income:"))
    assert f["income"] == round(income / 100)
    spend = sum(-t.amount_minor for t in july if t.amount_minor < 0 and t.category not in ("Transfers:Self", "Investments"))
    assert f["expenses"] == round(spend / 100)


def test_verifier_flags_invented_numbers():
    facts = {"income": 145000, "expenses": 98765, "top_categories": [{"category": "Housing:Rent", "amount": 32000,
                                                                      "share_pct": 32}]}
    assert ungrounded_numbers("Rent was ₹32,000 (32% of spend), income ₹1,45,000.", facts) == []
    assert ungrounded_numbers("You spent ₹48,200 on food.", facts) == ["48,200"]
    assert ungrounded_numbers("3 subscriptions renewed in 2026.", facts) == []


def test_report_retries_then_strips_ungrounded_sentences(loaded, settings):
    process_pending(loaded, FakeLLM(parse_handler=keyword_parse_handler), settings)
    drafts = [
        ReportNarrative(headline="A good month", highlights=["You spent ₹99,999 on snacks."], watch_outs=[],
                        suggestions=["Keep it up."]),
        ReportNarrative(headline="A good month", highlights=["You spent ₹88,888 on snacks.", "Income was steady."],
                        watch_outs=[], suggestions=["Keep it up."]),
    ]

    def handler(purpose, instructions, input, schema):
        return drafts.pop(0) if drafts else drafts
    r = write_report(loaded, FakeLLM(parse_handler=handler), "2026-07", settings, max_attempts=2)
    assert r.attempts == 2 and r.removed_sentences == ["You spent ₹88,888 on snacks."]
    assert r.narrative.highlights == ["Income was steady."]
    assert "99,999" not in r.markdown and "88,888" not in r.markdown and "## Where the money went" in r.markdown


def test_report_without_llm_is_still_useful(loaded, settings):
    r = write_report(loaded, None, "2026-08", settings)
    assert r.narrative is None and "**Income**" in r.markdown and "Recurring payments" in r.markdown
