import io

import pytest
from fastapi.testclient import TestClient

from ledger_agent.api import create_app
from ledger_agent.datagen import demo_pdf_month, savings_statement_pdf
from ledger_agent.ingest.importer import import_statement
from ledger_agent.ingest.pdf_reader import PdfPasswordRequired, read_pdf_table
from ledger_agent.pdfwrite import Page, build_pdf
from ledger_agent.service import LedgerService


def savings_rows(dataset):
    return [t for t in dataset.labels if t.account == "HDFC Savings"]


def test_pdf_statement_rebuilds_every_row_and_reconciles(conn, dataset):
    name, data, truth = demo_pdf_month(dataset)
    r = import_statement(conn, None, "HDFC Savings", name, data)
    assert (r.rows_new, r.rows_rejected, r.balance_check, r.profile_name) == (len(truth), 0, "ok", "heuristic")
    got = conn.execute("SELECT date, amount_minor, description FROM transactions ORDER BY id").fetchall()
    assert [tuple(g) for g in got] == [(t.day.isoformat(), t.amount_minor, t.description) for t in truth]


def test_wrapped_narrations_page_breaks_and_footers(dataset):
    rows = savings_rows(dataset)
    data = savings_statement_pdf(rows, 150000 * 100, (rows[0].day, rows[-1].day), rows_per_page=7)  # 13 pages
    table = read_pdf_table(data)
    assert len(table.rows) == len(rows)                                   # repeated headers aren't rows
    descs = [r[1] for r in table.rows]
    assert descs == [t.description for t in rows]                         # wrapped tails rejoined exactly
    assert not any("End of Statement" in d or "Page " in d for d in descs)


def test_same_statement_as_csv_then_pdf_is_all_duplicates(conn, dataset):
    for m in dataset.months:
        import_statement(conn, None, "HDFC Savings", f"{m}.csv", dataset.files[f"hdfc_savings_{m}.csv"])
    rows = savings_rows(dataset)
    pdf = savings_statement_pdf(rows, 150000 * 100, (rows[0].day, rows[-1].day))
    r = import_statement(conn, None, "HDFC Savings", "all.pdf", pdf)
    assert r.rows_new == 0 and r.rows_duplicate == len(rows) and r.balance_check == "ok"


def _locked(data: bytes, password: str) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    w.encrypt(password, algorithm="AES-256")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_password_protected_pdf(conn, dataset):
    name, data, truth = demo_pdf_month(dataset)
    locked = _locked(data, "SHAR0101")
    with pytest.raises(PdfPasswordRequired, match="password-protected"):
        import_statement(conn, None, "HDFC Savings", name, locked)
    with pytest.raises(PdfPasswordRequired, match="didn't open"):
        import_statement(conn, None, "HDFC Savings", name, locked, password="wrong")
    assert import_statement(conn, None, "HDFC Savings", name, locked, password="SHAR0101").rows_new == len(truth)


def test_pdf_without_a_text_layer_is_refused_clearly(conn):
    blank = build_pdf([Page()])
    with pytest.raises(ValueError, match="no text layer"):
        import_statement(conn, None, "X", "scan.pdf", blank)


def test_pdf_over_http_with_password(settings, dataset):
    app = create_app(settings, lambda: LedgerService(settings, llm=None))
    c = TestClient(app)
    name, data, truth = demo_pdf_month(dataset)
    locked = _locked(data, "pw")
    r = c.post("/v1/imports", data={"account": "HDFC Savings"}, files={"file": (name, locked, "application/pdf")})
    assert r.status_code == 422 and "password" in r.json()["detail"]
    r = c.post("/v1/imports", data={"account": "HDFC Savings", "password": "pw"},
               files={"file": (name, locked, "application/pdf")})
    assert r.status_code == 200 and r.json()["rows_new"] == len(truth) and r.json()["balance_check"] == "ok"
