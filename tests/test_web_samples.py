"""Statements from someone else's generator (sample_data/web/SOURCES.md), checked against its own answers.

The PDF reader was written against our generated statements. These two come from a public dataset with a
different layout, a rotated watermark, dates with times and page-relative spacing. They are the closest
thing to an unseen bank the tests can run offline."""

import json
from datetime import date
from pathlib import Path

import pytest

from ledger_agent.ingest.normalize import detect_date_format, parse_date
from ledger_agent.ingest.pdf_reader import _Chunk, _separate_numbers, read_pdf_table
from ledger_agent.ingest.profiles import check_profile, heuristic_profile

WEB = Path(__file__).resolve().parent.parent / "sample_data" / "web" / "statements"


def _answer(t: dict) -> tuple[date, int, int]:
    if "debit" in t:                                   # type 1: debit / credit / balance
        return (date.fromisoformat(t["date"][:10]), round(((t["credit"] or 0) - (t["debit"] or 0)) * 100),
                round(t["balance"] * 100))
    d, m, y = t["date"].split("/")                     # type 2: amount + CR/DR, available balance
    sign = -1 if t["cr_dr"] == "DR" else 1
    return date(int(y), int(m), int(d)), sign * round(t["transaction_amount"] * 100), round(t["available_balance"] * 100)


@pytest.mark.parametrize("name", ["agami_type1_00001", "agami_type2_00003"])
def test_third_party_statement_matches_its_answers_to_the_paisa(name):
    truth = json.loads((WEB / f"{name}.json").read_text(encoding="utf-8"))["transactions"]
    table = read_pdf_table((WEB / f"{name}.pdf").read_bytes())
    assert len(table.rows) == len(truth)               # every row found, across pages, under the watermark
    check = check_profile(heuristic_profile(table), table)
    assert check.parse_rate > 0.98
    for row in check.parsed:
        assert (row.date, row.amount_minor, row.balance_minor) == _answer(truth[row.row_index]), row
    # the only rows left out are the failed ones, which carry no amount
    assert all(truth[i]["description"].startswith("FAILED-") for i, _ in check.rejects)
    assert not any("SYNTHETIC DATA" in c for r in table.rows for c in r)


def test_their_balances_do_not_reconcile_so_the_sensor_refuses_them():
    """Not a reader bug: the dataset's own running balance breaks, and refusing that is the sensor's job."""
    for name in ["agami_type1_00001", "agami_type2_00003"]:
        tx = json.loads((WEB / f"{name}.json").read_text(encoding="utf-8"))["transactions"]
        answers = [_answer(t) for t in tx if not t["failed"]]
        breaks = sum(1 for a, b in zip(answers, answers[1:]) if b[2] != a[2] + b[1])
        assert breaks > 5
        table = read_pdf_table((WEB / f"{name}.pdf").read_bytes())
        check = check_profile(heuristic_profile(table), table)
        assert check.balance_check == "mismatch" and not check.ok


@pytest.mark.parametrize("value,want", [
    ("01-01-2024 11:30:55", date(2024, 1, 1)),
    ("10/01/2024 09:07:44 PM", date(2024, 1, 10)),
    ("2024-03-05T10:00", date(2024, 3, 5)),
    ("05 Aug 2026", date(2026, 8, 5)),
])
def test_dates_with_a_time_keep_the_day(value, want):
    assert parse_date(value) == want


def test_date_format_detection_ignores_times():
    assert detect_date_format(["13-01-2024 11:30:55", "02-02-2024 09:00:01"]) == "%d-%m-%Y"


def test_two_amounts_never_share_a_column():
    # "DR  99.33     10,330,407.08": the short amount ends nearer the balance column than its own
    chunks = [_Chunk(0, 2, "DR"), _Chunk(10, 15, "99.33"), _Chunk(20, 33, "10,330,407.08")]
    assert _separate_numbers(chunks, [0, 2, 2]) == [0, 1, 2]
    assert _separate_numbers(chunks, [0, 1, 2]) == [0, 1, 2]          # already apart: unchanged
