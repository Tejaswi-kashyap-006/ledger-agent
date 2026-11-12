from datetime import date

from ledger_agent.agent.loop import ask
from ledger_agent.agent.tools import TOOLS, ToolContext, execute
from ledger_agent.categorize.pipeline import process_pending
from ledger_agent.categorize.review import set_category
from ledger_agent.llm.fake import FakeLLM, answer_step, keyword_parse_handler, tool_step


def outputs(llm, i):
    return [it["output"] for it in llm.step_calls[i]["items"] if it.get("type") == "function_call_output"]


def test_tool_then_answer(loaded, settings):
    llm = FakeLLM(steps=[
        tool_step(("spending_summary", {"start_date": "2026-07-01", "end_date": "2026-07-31",
                                        "group_by": "category", "direction": "debit"})),
        answer_step("You spent ₹X on food delivery."),
    ])
    a = ask(loaded, llm, settings, "How much did I spend in July?", today=date(2026, 9, 1))
    assert a.stop == "done" and a.turns == 2 and a.tool_calls[0]["name"] == "spending_summary"
    out = outputs(llm, 1)[0]
    assert "TOTAL" in out and "₹" in out
    assert "Today is 2026-09-01" in llm.step_calls[0]["instructions"]


def test_tool_errors_are_observations(loaded, settings):
    llm = FakeLLM(steps=[
        tool_step(("spending_summary", {"start_date": "July", "end_date": "2026-07-31", "group_by": "category",
                                        "direction": "debit"}),
                  ("run_sql", {"query": "DELETE FROM transactions"}),
                  ("does_not_exist", {})),
        answer_step("Sorry."),
    ])
    ask(loaded, llm, settings, "q")
    outs = outputs(llm, 1)
    assert "YYYY-MM-DD" in outs[0] and "not allowed" in outs[1] and "Unknown tool" in outs[2]


def test_memory_tool_persists_into_next_question(loaded, settings):
    llm = FakeLLM(steps=[
        tool_step(("memory_update", {"block": "household", "old": "", "new": "Landlord is Ramesh Kumar."})),
        answer_step("Noted - I'll remember your landlord."),
        answer_step("ok"),
    ])
    a1 = ask(loaded, llm, settings, "My landlord is Ramesh Kumar")
    assert "Landlord is Ramesh Kumar." not in llm.step_calls[0]["instructions"]
    ask(loaded, llm, settings, "anything", conversation_id="other")
    assert "Landlord is Ramesh Kumar." in llm.step_calls[2]["instructions"]
    assert a1.stop == "done"


def test_facts_are_recalled_when_relevant(loaded, settings):
    llm = FakeLLM(steps=[tool_step(("remember", {"fact": "User is saving for a trip to Japan in December",
                                                 "importance": 7})),
                         answer_step("saved"), answer_step("ok"), answer_step("ok")])
    ask(loaded, llm, settings, "remember I'm saving for Japan")
    ask(loaded, llm, settings, "How is my Japan trip saving going?")
    assert "Japan" in llm.step_calls[2]["instructions"].split("<recalled_facts>")[1]


def test_conversation_history_is_replayed(loaded, settings):
    llm = FakeLLM(steps=[answer_step("first answer"), answer_step("second")])
    a = ask(loaded, llm, settings, "first question")
    ask(loaded, llm, settings, "follow up", conversation_id=a.conversation_id)
    items = llm.step_calls[1]["items"]
    assert items[0] == {"role": "user", "content": "first question"}
    assert items[1] == {"role": "assistant", "content": "first answer"}


def test_max_turns(loaded, settings):
    settings.agent_max_turns = 2
    step = lambda items: tool_step(("recurring_payments", {}))  # noqa: E731
    a = ask(loaded, FakeLLM(steps=[step, step]), settings, "loop forever")
    assert a.stop == "max_turns" and a.turns == 2


def test_proposals_never_touch_user_verified_rows(loaded, settings):
    process_pending(loaded, FakeLLM(parse_handler=keyword_parse_handler), settings)
    ids = [r["id"] for r in loaded.execute("SELECT id FROM transactions WHERE merchant='TRUFFLES'")]
    set_category(loaded, ids[0], "Food:Dining Out")
    out, err = execute(ToolContext(loaded, settings), "propose_recategorization",
                       {"transaction_ids": ids, "category": "Travel:Hotels", "reason": "test"})
    assert not err and "Queued 2" in out
    row = loaded.execute("SELECT category, status FROM transactions WHERE id=?", (ids[0],)).fetchone()
    assert (row["category"], row["status"]) == ("Food:Dining Out", "categorized")


def test_tool_schemas_are_strict():
    for name, (spec, _) in TOOLS.items():
        p = spec["parameters"]
        assert spec["strict"] and p["additionalProperties"] is False and set(p["required"]) == set(p["properties"]), name
