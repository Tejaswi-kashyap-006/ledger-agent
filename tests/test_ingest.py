import pytest

from ledger_agent.ingest.csv_reader import read_table
from ledger_agent.ingest.importer import import_statement
from ledger_agent.ingest.profiles import ImportProfile, check_profile, heuristic_profile
from ledger_agent.llm.client import LLMError
from ledger_agent.llm.fake import FakeLLM


def test_reader_skips_preamble_and_footer(dataset):
    t = read_table(dataset.files["hdfc_savings_2026-06.csv"])
    assert t.header[0] == "Date" and t.header[-1] == "Closing Balance"
    assert len(t.preamble) >= 3 and not any("End of Statement" in r[0] for r in t.rows)


def test_heuristic_profiles_for_both_formats(dataset):
    bank = heuristic_profile(read_table(dataset.files["hdfc_savings_2026-06.csv"]))
    card = heuristic_profile(read_table(dataset.files["icici_card_2026-06.csv"]))
    assert bank.amount_mode == "split" and bank.balance_column == "Closing Balance" and bank.date_format == "%d/%m/%y"
    assert card.amount_mode == "with_type" and card.type_column == "Type" and card.date_format == "%d-%b-%Y"


def test_balance_reconciliation_catches_wrong_sign(dataset):
    table = read_table(dataset.files["hdfc_savings_2026-06.csv"])
    good = heuristic_profile(table)
    assert check_profile(good, table).balance_check == "ok"
    swapped = good.model_copy(update={"debit_column": good.credit_column, "credit_column": good.debit_column})
    check = check_profile(swapped, table)
    assert not check.ok and "reconcile" in " ".join(check.errors)


def test_import_dedupes_overlaps_and_reimports(conn, dataset):
    total_new = total_dup = 0
    for m in dataset.months:
        for account, fname in dataset.files_by_month[m]:
            r = import_statement(conn, None, account, fname, dataset.files[fname])
            total_new, total_dup = total_new + r.rows_new, total_dup + r.rows_duplicate
            assert r.rows_rejected == 0
    assert total_new == len(dataset.labels) and total_dup == dataset.expected_duplicates
    again = import_statement(conn, None, "HDFC Savings", "x.csv", dataset.files["hdfc_savings_2026-06.csv"])
    assert again.rows_new == 0 and again.rows_duplicate == again.rows_total


def test_profile_is_remembered_by_signature(conn, dataset):
    import_statement(conn, None, "HDFC Savings", "a.csv", dataset.files["hdfc_savings_2026-06.csv"])
    import_statement(conn, None, "HDFC Savings", "b.csv", dataset.files["hdfc_savings_2026-07.csv"])
    rows = conn.execute("SELECT source, uses FROM import_profiles").fetchall()
    assert [(r["source"], r["uses"]) for r in rows] == [("heuristic", 2)]


WEIRD = b"""Posted On;Txn Remarks;Value;Nature
03.06.2026;UPI-SWIGGY-SWIGGY@ICICI-ICIC0DC0099-412345678901-UPI;450,00;D
04.06.2026;NEFT CR-ACME-SALARY;145000,00;C
"""


def weird_profile(**over):
    base = dict(name="weird", date_column="Posted On", date_format="%d.%m.%Y", description_columns=["Txn Remarks"],
                amount_mode="with_type", debit_column=None, credit_column=None, amount_column="Value",
                type_column="Nature", positive_is_debit=False, balance_column=None)
    return ImportProfile(**{**base, **over})


def test_unknown_format_learned_by_llm_with_feedback_retry(conn):
    # the heuristic can't read this file; the LLM's 1st proposal is wrong, the 2nd (after feedback) right
    WEIRD_OK = WEIRD.replace(b"450,00", b"450.00").replace(b"145000,00", b"145000.00")
    proposals = [weird_profile(date_column="Value"), weird_profile()]
    llm = FakeLLM(parse_handler=lambda *a: proposals.pop(0))
    r = import_statement(conn, llm, "Other Bank", "weird.csv", WEIRD_OK)
    assert r.rows_new == 2 and r.profile_name == "weird"
    assert "previous_attempt_errors" in llm.parse_calls[1]["input"]
    assert conn.execute("SELECT source FROM import_profiles").fetchone()["source"] == "llm"
    # second import of the same layout: no LLM needed
    llm2 = FakeLLM(parse_handler=lambda *a: pytest.fail("should reuse stored profile"))
    assert import_statement(conn, llm2, "Other Bank", "weird2.csv", WEIRD_OK).rows_duplicate == 2


def test_unlearnable_format_is_refused_not_guessed(conn):
    llm = FakeLLM(parse_handler=lambda *a: LLMError("nope"))
    with pytest.raises(ValueError, match="Could not learn"):
        import_statement(conn, llm, "Other Bank", "weird.csv", WEIRD)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0   # atomic: nothing half-imported
