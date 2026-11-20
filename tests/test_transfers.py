from ledger_agent.categorize.pipeline import process_pending
from ledger_agent.categorize.review import set_category
from ledger_agent.categorize.rules import add_rule
from ledger_agent.llm.fake import FakeLLM

from test_pipeline import const_handler, txns_in

_n = iter(range(1, 10_000))


def account(conn, name):
    a = conn.execute("INSERT INTO accounts (name) VALUES (?) RETURNING id", (name,)).fetchone()["id"]
    imp = conn.execute("INSERT INTO imports (account_id, filename, file_sha256) VALUES (?, 'x.csv', 'h') RETURNING id",
                       (a,)).fetchone()["id"]
    return a, imp


def txn(conn, acct, date, amount_minor, description, merchant=""):
    a, imp = acct
    return conn.execute(
        "INSERT INTO transactions (account_id, import_id, date, amount_minor, description, merchant, fingerprint)"
        " VALUES (?,?,?,?,?,?,?) RETURNING id", (a, imp, date, amount_minor, description, merchant, f"fp{next(_n)}"),
    ).fetchone()["id"]


def row(conn, txn_id):
    return conn.execute("SELECT category, category_source, status FROM transactions WHERE id = ?", (txn_id,)).fetchone()


def test_card_bill_is_a_transfer_without_memory_or_model(conn, settings):
    savings, card = account(conn, "HDFC Savings"), account(conn, "ICICI Credit Card")
    out = txn(conn, savings, "2026-06-24", -1845000, "BIL/ONL/123/ICICI CREDIT CARD/Card bill", "ICICI CREDIT CARD")
    back = txn(conn, card, "2026-06-25", 1845000, "PAYMENT RECEIVED - THANK YOU")
    swiggy = txn(conn, savings, "2026-06-24", -61000, "UPI/SWIGGY", "SWIGGY")
    llm = FakeLLM(parse_handler=const_handler("Loans & EMI", 0.95))      # the live model's confident mistake
    r = process_pending(conn, llm, settings)
    for t in (out, back):
        assert tuple(row(conn, t)) == ("Transfers:Self", "rule", "categorized")
    assert r.stats.transfer_matches == 2
    sent = [t["description"] for c in llm.parse_calls for t in txns_in(c["input"])]
    assert sent == ["UPI/SWIGGY"]                                          # only the unknown went to the model
    assert row(conn, swiggy)["category_source"] == "llm"


def test_later_statement_overturns_the_models_earlier_answer(conn, settings):
    savings, card = account(conn, "HDFC Savings"), account(conn, "ICICI Credit Card")
    out = txn(conn, savings, "2026-06-24", -1845000, "ICICI CREDIT CARD bill", "ICICI CREDIT CARD")
    process_pending(conn, FakeLLM(parse_handler=const_handler("Loans & EMI", 0.95)), settings)
    assert row(conn, out)["category"] == "Loans & EMI"
    txn(conn, card, "2026-06-26", 1845000, "PAYMENT RECEIVED")             # the card statement arrives later
    process_pending(conn, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings)
    assert tuple(row(conn, out)) == ("Transfers:Self", "rule", "categorized")


def test_ambiguous_or_distant_amounts_are_not_matched(conn, settings):
    savings, card, wallet = account(conn, "Savings"), account(conn, "Card"), account(conn, "Wallet")
    a = txn(conn, savings, "2026-06-10", -50000, "UPI/FRIEND ONE")
    b = txn(conn, wallet, "2026-06-10", -50000, "UPI/FRIEND TWO")
    c = txn(conn, card, "2026-06-11", 50000, "REFUND")                     # mirrors two entries: ambiguous
    far = txn(conn, savings, "2026-06-01", -99900, "UPI/SHOP")
    txn(conn, card, "2026-06-20", 99900, "REFUND")                         # same amount, 19 days later
    same = txn(conn, savings, "2026-06-15", -20000, "ATM")
    txn(conn, savings, "2026-06-15", 20000, "ATM REVERSAL")                # same account: not a transfer
    process_pending(conn, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings)
    for t in (a, b, c, far, same):
        assert row(conn, t)["category"] == "Other"


def test_rules_and_human_decisions_win(conn, settings):
    savings, card = account(conn, "Savings"), account(conn, "Card")
    add_rule(conn, "merchant", "LOAN CO", "Loans & EMI", source="user")
    ruled = txn(conn, savings, "2026-06-05", -300000, "LOAN CO EMI", "LOAN CO")
    txn(conn, card, "2026-06-05", 300000, "CREDIT")
    process_pending(conn, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings)
    assert tuple(row(conn, ruled)) == ("Loans & EMI", "rule", "categorized")

    mine = txn(conn, savings, "2026-07-05", -700000, "NEFT TO DAD", "DAD")
    process_pending(conn, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings)
    set_category(conn, mine, "Gifts & Donations", 2)
    txn(conn, card, "2026-07-06", 700000, "CREDIT")
    process_pending(conn, FakeLLM(parse_handler=const_handler("Other", 0.9)), settings)
    assert tuple(row(conn, mine)) == ("Gifts & Donations", "user", "categorized")
