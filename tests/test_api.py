import pytest
from fastapi.testclient import TestClient

from ledger_agent.api import create_app
from ledger_agent.llm.fake import FakeLLM, answer_step, keyword_parse_handler, tool_step
from ledger_agent.service import LedgerService


@pytest.fixture
def client_factory(settings):
    def make(api_key=None, steps=None):
        settings.api_key = api_key
        factory = lambda: LedgerService(settings, llm=FakeLLM(parse_handler=keyword_parse_handler,  # noqa: E731
                                                                steps=list(steps or [])))
        return TestClient(create_app(settings, factory))
    return make


def test_end_to_end_over_http(client_factory, dataset):
    c = client_factory()
    assert c.get("/healthz").json() == {"status": "ok", "llm": True}
    f = dataset.files["hdfc_savings_2026-06.csv"]
    r = c.post("/v1/imports", data={"account": "HDFC Savings"}, files={"file": ("june.csv", f, "text/csv")})
    assert r.status_code == 200 and r.json()["rows_new"] == 28 and r.json()["balance_check"] == "ok"

    run = c.post("/v1/process").json()
    assert run["status"] == "completed" and run["stats"]["processed"] == 28

    queue = c.get("/v1/review").json()
    assert queue and all(q["review_reason"] for q in queue)
    fixed = c.post(f"/v1/transactions/{queue[0]['id']}/category", json={"category": "Food:Dining Out"}).json()
    assert fixed["category"] == "Food:Dining Out"

    stats = c.get("/v1/stats").json()
    assert stats["transactions"] == 28 and stats["verified_labels"] == 1 and 0 < stats["automation_rate"] <= 1

    md = c.get("/v1/reports/2026-06", params={"format": "md"})
    assert md.status_code == 200 and "Where the money went" in md.text


def test_validation_and_not_found_errors(client_factory):
    c = client_factory()
    assert c.post("/v1/transactions/999/category", json={"category": "Other"}).status_code == 404
    assert c.post("/v1/rules", json={"pattern": "X", "category": "Nope"}).status_code == 422
    assert c.post("/v1/imports", data={"account": "A"},
                  files={"file": ("x.csv", b"just,some\nnonsense", "text/csv")}).status_code == 422


def test_auth_required_when_configured(client_factory):
    c = client_factory(api_key="s3cret")
    assert c.get("/v1/stats").status_code == 401
    assert c.get("/v1/stats", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/v1/stats", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/healthz").status_code == 200                      # probes stay unauthenticated


def test_chat_endpoint(client_factory):
    c = client_factory(steps=[tool_step(("recurring_payments", {})), answer_step("No subscriptions yet.")])
    r = c.post("/v1/chat", json={"message": "What subscriptions do I have?"}).json()
    assert r["answer"] == "No subscriptions yet." and r["tool_calls"][0]["name"] == "recurring_payments"


def test_ui_read_endpoints(client_factory, dataset):
    c = client_factory()
    c.post("/v1/imports", data={"account": "HDFC Savings"},
           files={"file": ("june.csv", dataset.files["hdfc_savings_2026-06.csv"], "text/csv")})
    assert "Food:Delivery" in c.get("/v1/categories").json()
    assert c.get("/v1/months").json() == ["2026-06"]
    page = c.get("/v1/transactions", params={"q": "swiggy", "limit": 2}).json()
    assert page["total"] >= 2 and len(page["items"]) == 2 and page["items"][0]["account"] == "HDFC Savings"
    assert c.get("/v1/facts/2026-06").json()["month"] == "2026-06"


def test_ui_support_endpoints(client_factory, dataset):
    c = client_factory()
    c.post("/v1/imports", data={"account": "HDFC Savings"},
           files={"file": ("june.csv", dataset.files["hdfc_savings_2026-06.csv"], "text/csv")})
    c.post("/v1/process")
    assert c.get("/v1/accounts").json()[0]["transactions"] == 28
    trend = c.get("/v1/trend").json()
    assert trend[0]["month"] == "2026-06" and trend[0]["money_out"] > 0
    blocks = {b["label"]: b for b in c.get("/v1/memory/blocks").json()}
    assert set(blocks) == {"household", "preferences", "goals"}
    r = c.put("/v1/memory/blocks/household", json={"value": "Landlord is Ramesh Kumar."})
    assert r.status_code == 200 and r.json()["value"] == "Landlord is Ramesh Kumar."
    assert c.put("/v1/memory/blocks/household", json={"value": "x" * 5000}).status_code == 422
    assert c.put("/v1/memory/blocks/nope", json={"value": "x"}).status_code == 404
    rule = c.post("/v1/rules", json={"pattern": "zomato", "category": "Food:Delivery"}).json()["id"]
    assert c.delete(f"/v1/rules/{rule}").status_code == 204
    assert c.delete(f"/v1/rules/{rule}").status_code == 404
    assert c.get("/v1/conversations/none").json() == []


def test_serves_built_ui_with_spa_fallback(settings, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Ledger</title>")
    (static / "assets" / "app-abc123.js").write_text("console.log(1)")
    c = TestClient(create_app(settings, lambda: LedgerService(settings, llm=None), static_dir=static))
    assert "<title>Ledger</title>" in c.get("/").text
    assert "<title>Ledger</title>" in c.get("/review").text                 # client-side route
    js = c.get("/assets/app-abc123.js")
    assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
    assert c.get("/v1/does-not-exist").status_code == 404                   # API 404s stay JSON 404s
    assert c.get("/healthz").json()["status"] == "ok"
    assert "<title>Ledger</title>" in c.get("/../../etc/passwd").text       # no traversal: falls back to index
