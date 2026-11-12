"""The memory lifecycle: correction -> verified label -> few-shot -> compiled rule -> propagation -> forgetting."""

import json

import pytest

from ledger_agent.categorize.pipeline import process_pending
from ledger_agent.categorize.review import accept_suggestion, review_queue, set_category
from ledger_agent.llm.fake import FakeLLM, keyword_parse_handler


def ids(conn, merchant):
    return [r["id"] for r in conn.execute("SELECT id FROM transactions WHERE merchant=? ORDER BY id", (merchant,))]


def test_correction_stores_verified_label(loaded, settings, keyword_llm):
    process_pending(loaded, keyword_llm, settings)
    t = ids(loaded, "MYNTRA DESIGNS")[0]
    r = set_category(loaded, t, "Shopping:Clothing")
    lab = loaded.execute("SELECT * FROM labels").fetchone()
    assert (lab["kind"], lab["old_category"], lab["category"]) == ("correction", "Shopping:Online", "Shopping:Clothing")
    assert r.rule_created is None                                  # one correction is not a pattern yet
    row = loaded.execute("SELECT category_source, confidence FROM transactions WHERE id=?", (t,)).fetchone()
    assert (row["category_source"], row["confidence"]) == ("user", 1.0)


def test_two_consistent_corrections_compile_a_rule_and_propagate(loaded, settings, keyword_llm):
    process_pending(loaded, keyword_llm, settings)
    a, b, c = ids(loaded, "MYNTRA DESIGNS")
    set_category(loaded, a, "Shopping:Clothing")
    r = set_category(loaded, b, "Shopping:Clothing")
    assert r.rule_created is not None and r.propagated == 1        # the 3rd Myntra row was fixed automatically
    third = loaded.execute("SELECT category, category_source FROM transactions WHERE id=?", (c,)).fetchone()
    assert (third["category"], third["category_source"]) == ("Shopping:Clothing", "rule")


def test_compiled_rule_means_no_more_llm_calls_for_that_merchant(conn, dataset, settings):
    from ledger_agent.ingest.importer import import_statement
    june = dataset.files_by_month["2026-06"]
    for acct, f in june:
        import_statement(conn, None, acct, f, dataset.files[f])
    process_pending(conn, FakeLLM(parse_handler=keyword_parse_handler), settings)
    for t in ids(conn, "THIRD WAVE COFFEE")[:2]:
        set_category(conn, t, "Food:Dining Out")
    for acct, f in dataset.files_by_month["2026-07"]:
        import_statement(conn, None, acct, f, dataset.files[f])
    llm = FakeLLM(parse_handler=keyword_parse_handler)
    process_pending(conn, llm, settings)
    sent = [t["merchant"] for c in llm.parse_calls
            for t in json.loads(c["input"].split("<transactions>")[1].split("</transactions>")[0])]
    assert sent and "THIRD WAVE COFFEE" not in sent
    july = conn.execute("SELECT DISTINCT category_source FROM transactions WHERE merchant='THIRD WAVE COFFEE' "
                        "AND date LIKE '2026-07%'").fetchall()
    assert [r[0] for r in july] == ["rule"]


def test_verified_examples_are_fed_to_the_model(loaded, settings, keyword_llm):
    process_pending(loaded, keyword_llm, settings, limit=20)
    t = ids(loaded, "TRUFFLES")[0]
    set_category(loaded, t, "Food:Dining Out")
    llm = FakeLLM(parse_handler=keyword_parse_handler)
    process_pending(loaded, llm, settings)
    examples = [json.loads(c["input"].split("<verified_examples>")[1].split("</verified_examples>")[0])
                for c in llm.parse_calls]
    assert any(e["merchant"] == "TRUFFLES" and e["category"] == "Food:Dining Out" for ex in examples for e in ex)


def test_contradicting_correction_invalidates_compiled_rule(loaded, settings, keyword_llm):
    process_pending(loaded, keyword_llm, settings)
    a, b, c = ids(loaded, "SUNITA DEVI")
    set_category(loaded, a, "Gifts & Donations")
    set_category(loaded, b, "Gifts & Donations")
    assert loaded.execute("SELECT COUNT(*) FROM rules WHERE active=1 AND pattern='SUNITA DEVI'").fetchone()[0] == 1
    r = set_category(loaded, c, "Transfers:To People")                  # the human changed their mind
    assert r.rules_invalidated == 1
    assert loaded.execute("SELECT COUNT(*) FROM rules WHERE active=1 AND pattern='SUNITA DEVI'").fetchone()[0] == 0


def test_review_queue_and_accept(loaded, settings):
    process_pending(loaded, None, settings)                               # no model: everything needs a human
    q = review_queue(loaded, 500)
    assert len(q) == 121 and {i["review_reason"] for i in q} == {"no_llm", "suspicious_text"}
    with pytest.raises(ValueError):
        accept_suggestion(loaded, q[0]["id"])                              # nothing to accept
    with pytest.raises(ValueError):
        set_category(loaded, q[0]["id"], "Not A Category")


def test_audit_sample_catches_confident_errors_and_flags_siblings(loaded, settings, keyword_llm):
    from ledger_agent.categorize.review import audit_sample
    process_pending(loaded, keyword_llm, settings)
    # the keyword model confidently files THIRD WAVE COFFEE under "Fees" (matches FEE in COFFEE)
    wrong = loaded.execute("SELECT COUNT(*) FROM transactions WHERE merchant='THIRD WAVE COFFEE' "
                           "AND category='Fees & Bank Charges' AND status='categorized'").fetchone()[0]
    assert wrong == 9
    sample = audit_sample(loaded, 5)
    assert len({s["merchant"] for s in sample}) == len(sample)            # one row per merchant
    twc = next(s for s in sample if s["merchant"] == "THIRD WAVE COFFEE")
    r = set_category(loaded, twc["id"], "Food:Dining Out")
    assert r.siblings_flagged == 8
    flagged = loaded.execute("SELECT COUNT(*) FROM transactions WHERE merchant='THIRD WAVE COFFEE' "
                             "AND review_reason='sibling_of_correction'").fetchone()[0]
    assert flagged == 8
    assert "THIRD WAVE COFFEE" not in {s["merchant"] for s in audit_sample(loaded, 50)}   # verified -> not re-audited
