import pytest
from fastapi.testclient import TestClient

from ledger_agent.api import create_app
from ledger_agent.categorize.review import review_queue
from ledger_agent.datagen import demo_receipts, receipt_invoice_pdf
from ledger_agent.llm.fake import FakeLLM
from ledger_agent.receipts import NotAReceipt, add_receipt, attach, get_receipt, list_receipts
from ledger_agent.service import LedgerService

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64          # the reader is faked, so any PNG-shaped bytes will do


def reader(read: dict):
    return FakeLLM(parse_handler=lambda purpose, instructions, input, schema: read)


def read_of(merchant, day, total, items=None):
    items = items if items is not None else [{"description": "thing", "amount": total, "category": "Other"}]
    return {"is_receipt": True, "merchant": merchant, "date": day, "total": total, "items": items}


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def txn_id(conn, day, merchant_like):
    return conn.execute("SELECT id FROM transactions WHERE date = ? AND description LIKE ?",
                        (day, f"%{merchant_like}%")).fetchone()["id"]


def test_receipt_attaches_to_its_bank_entry_and_never_adds_money(loaded, dataset):
    spec = next(s for s in demo_receipts(dataset) if s.merchant == "Apollo Pharmacy")
    before = count(loaded, "transactions")
    r = add_receipt(loaded, reader(spec.as_read()), spec.filename, PNG)
    assert r.match_status == "matched" and r.transaction_id == txn_id(loaded, "2026-08-16", "APOLLO")
    assert r.total_minor == 89000 and r.items_add_up and len(r.items) == 7
    assert {i["category"] for i in r.items} == {"Health:Pharmacy", "Personal Care"}     # one payment, two kinds
    assert count(loaded, "transactions") == before                                    # evidence, not a new entry


def test_same_file_twice_is_one_receipt_and_one_model_call(loaded, dataset):
    spec = demo_receipts(dataset)[0]
    llm = reader(spec.as_read())
    first = add_receipt(loaded, llm, spec.filename, PNG)
    again = add_receipt(loaded, llm, "copy.png", PNG)
    assert again.duplicate and again.receipt_id == first.receipt_id
    assert len(llm.parse_calls) == 1 and count(loaded, "receipts") == 1


def test_amount_must_agree_to_the_paisa(loaded):
    r = add_receipt(loaded, reader(read_of("Apollo Pharmacy", "2026-08-16", 890.5)), "a.png", PNG)
    assert r.match_status == "unmatched" and r.transaction_id is None                 # a misread total is safe
    assert r.candidates and r.candidates[0]["description"].find("APOLLO") >= 0      # offered to a person instead


def test_same_amount_same_day_is_decided_by_name_or_left_to_a_person(conn):
    from test_transfers import account, txn
    acct = account(conn, "Savings")
    ids = {m: txn(conn, acct, "2026-08-10", -50000, f"UPI/DR/1/{m}/x@ybl", m) for m in ("ZEPTO", "SWIGGY", "BLINKIT")}
    r = add_receipt(conn, reader(read_of("Zepto", "2026-08-10", 500)), "z.png", PNG)
    assert r.transaction_id == ids["ZEPTO"]                                   # three ₹500 entries: the name decides
    # an unknown shop at ₹500 matches the two remaining entries equally: nobody guesses
    r2 = add_receipt(conn, reader(read_of("Corner Store", "2026-08-10", 500)), "c.png", PNG + b"2")
    assert r2.match_status == "unmatched" and {c["id"] for c in r2.candidates} == {ids["SWIGGY"], ids["BLINKIT"]}
    assert attach(conn, r2.receipt_id, ids["SWIGGY"]).match_status == "user"
    with pytest.raises(ValueError, match="already has receipt"):
        attach(conn, r2.receipt_id, ids["ZEPTO"])
    assert attach(conn, r2.receipt_id, None).match_status == "unmatched"


def test_sensors_flag_items_that_dont_add_up_and_refuse_non_receipts(loaded):
    items = [{"description": "a", "amount": 500, "category": "Other"}]
    r = add_receipt(loaded, reader(read_of("Apollo Pharmacy", "2026-08-16", 890, items)), "a.png", PNG)
    assert r.match_status == "matched" and not r.items_add_up
    with pytest.raises(NotAReceipt):
        add_receipt(loaded, reader({"is_receipt": False, "merchant": "", "date": None, "total": 0, "items": []}),
                    "cat.png", PNG + b"cat")
    with pytest.raises(RuntimeError, match="needs a language model"):
        add_receipt(loaded, None, "x.png", PNG + b"x")
    with pytest.raises(ValueError, match="photo"):
        add_receipt(loaded, None, "x.txt", b"hello")


def test_pdf_invoice_is_sent_as_redacted_text_not_an_image(loaded, dataset):
    spec = next(s for s in demo_receipts(dataset) if s.kind == "pdf")
    llm = reader(spec.as_read())
    r = add_receipt(loaded, llm, spec.filename, receipt_invoice_pdf(spec))
    sent = llm.parse_calls[0]["input"]
    assert isinstance(sent, str) and "Atomic Habits" in sent and "<receipt_text>" in sent
    assert r.transaction_id == txn_id(loaded, "2026-08-16", "AMAZON") and r.items_add_up


def test_photo_is_sent_as_an_image_item(loaded, dataset):
    spec = demo_receipts(dataset)[0]
    llm = reader(spec.as_read())
    add_receipt(loaded, llm, spec.filename, PNG)
    content = llm.parse_calls[0]["input"][0]["content"]
    assert content[1]["type"] == "input_image" and content[1]["image_url"].startswith("data:image/png;base64,")


def test_review_card_and_ledger_see_the_receipt(loaded, dataset, settings):
    spec = demo_receipts(dataset)[0]
    t = txn_id(loaded, "2026-08-19", "TRUFFLES")
    loaded.execute("UPDATE transactions SET status = 'needs_review' WHERE id = ?", (t,))
    r = add_receipt(loaded, reader(spec.as_read()), spec.filename, PNG)
    assert {q["id"]: q["receipt_id"] for q in review_queue(loaded, 500)}[t] == r.receipt_id
    assert list_receipts(loaded)[0]["transaction_merchant"] == "TRUFFLES"
    assert get_receipt(loaded, r.receipt_id).candidates == []


def test_receipts_over_http(settings, dataset):
    spec = demo_receipts(dataset)[0]
    c = TestClient(create_app(settings, lambda: LedgerService(settings, llm=reader(spec.as_read()))))
    for account, name in (("HDFC Savings", "hdfc_savings_2026-08.csv"), ("ICICI Credit Card", "icici_card_2026-08.csv")):
        c.post("/v1/imports", data={"account": account}, files={"file": (name, dataset.files[name], "text/csv")})
    up = c.post("/v1/receipts", files={"file": (spec.filename, PNG, "image/png")})
    assert up.status_code == 200 and up.json()["match_status"] == "matched"
    rid = up.json()["receipt_id"]
    f = c.get(f"/v1/receipts/{rid}/file")
    assert f.content == PNG and f.headers["content-type"] == "image/png"
    assert f.headers["x-content-type-options"] == "nosniff"
    tx = c.get("/v1/transactions", params={"q": "TRUFFLES"}).json()["items"]
    assert [t["receipt_id"] for t in tx if t["date"] == "2026-08-19"] == [rid]
    assert c.post(f"/v1/receipts/{rid}/attach", json={"transaction_id": None}).json()["match_status"] == "unmatched"
    assert c.get("/v1/receipts").json()[0]["id"] == rid
    assert c.post("/v1/receipts", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 422
    assert c.delete(f"/v1/receipts/{rid}").status_code == 204
    assert c.get(f"/v1/receipts/{rid}").status_code == 404
