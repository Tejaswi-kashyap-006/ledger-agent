import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { SlipProvider } from "../components/Toast";
import type { ReviewItem } from "../lib/types";

vi.mock("../lib/api", async (orig) => {
  const actual = await orig<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      categories: vi.fn(async () => ["Food:Delivery", "Food:Dining Out", "Housing:Rent", "Income:Other", "Transfers:To People"]),
      review: vi.fn(),
      audit: vi.fn(),
      accept: vi.fn(),
      setCategory: vi.fn(),
    },
  };
});

import { api } from "../lib/api";
import { describeTool } from "./Ask";
import { Verified } from "./Reports";
import { ReviewPage } from "./Review";

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const ITEM = (over: Partial<ReviewItem> = {}): ReviewItem => ({
  id: 7, date: "2026-07-03", amount_minor: -3200000, merchant: "RAMESH KUMAR",
  description: "UPI/DR/[num-1458]/RAMESH KUMAR/SBIN/rent", suggestion: "Transfers:To People", confidence: 0.55,
  review_reason: "low_confidence", llm_reason: "payment to an individual", ...over,
});

function renderReview(mode: "review" | "audit" = "review") {
  return render(<MemoryRouter><SlipProvider><ReviewPage mode={mode} /></SlipProvider></MemoryRouter>);
}

const result = (category: string, extra = {}) => ({ transaction_id: 7, category, rule_created: null, rules_invalidated: 0, propagated: 0,
  siblings_flagged: 0, ...extra });

beforeEach(() => vi.clearAllMocks());

describe("Review", () => {
  it("Enter initials the pencilled suggestion, then the queue is re-read", async () => {
    mocked.review!.mockResolvedValueOnce([ITEM()]).mockResolvedValueOnce([]);
    mocked.accept!.mockResolvedValue(result("Transfers:To People"));
    renderReview();
    expect(await screen.findByRole("heading", { name: "RAMESH KUMAR" })).toBeInTheDocument();
    expect(screen.getByText(/55% confident/)).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(mocked.accept).toHaveBeenCalledWith(7));
    expect(await screen.findByText("All posted")).toBeInTheDocument();
  });

  it("number keys post under a quick-pick category and a learned rule is announced", async () => {
    mocked.review!.mockResolvedValueOnce([ITEM()]).mockResolvedValueOnce([]);
    mocked.setCategory!.mockResolvedValue(result("Food:Delivery", { rule_created: 3, propagated: 2 }));
    renderReview();
    await screen.findByRole("heading", { name: "RAMESH KUMAR" });
    // quick picks: 1 = the model's suggestion, then the common list: 2 = Food:Groceries, 3 = Food:Delivery
    await userEvent.keyboard("3");
    await waitFor(() => expect(mocked.setCategory).toHaveBeenCalledWith(7, "Food:Delivery"));
    expect(await screen.findByText("Rule learned for RAMESH KUMAR")).toBeInTheDocument();
    expect(screen.getByText(/2 more entries were posted/)).toBeInTheDocument();
  });

  it("explains when a correction sends the model's matching answers back to review", async () => {
    mocked.review!.mockResolvedValueOnce([ITEM()]).mockResolvedValueOnce([ITEM({ id: 8 }), ITEM({ id: 9 })]);
    mocked.setCategory!.mockResolvedValue(result("Housing:Rent", { siblings_flagged: 2 }));
    renderReview();
    await screen.findByRole("heading", { name: "RAMESH KUMAR" });
    await userEvent.keyboard("8");
    expect(await screen.findByText("2 earlier answers for RAMESH KUMAR sent back for review")).toBeInTheDocument();
  });

  it("S skips, and suspicious entries can't be accepted with one keystroke", async () => {
    mocked.review!.mockResolvedValue([
      ITEM({ id: 1, merchant: "IGNORE PREVIOUS", review_reason: "suspicious_text", suggestion: "Income:Other" }),
      ITEM({ id: 2, merchant: "SWIGGY" }),
    ]);
    renderReview();
    await screen.findByRole("heading", { name: "IGNORE PREVIOUS" });
    expect(screen.getByRole("button", { name: /Initial & post/ })).toBeDisabled();
    await userEvent.keyboard("{Enter}");
    expect(mocked.accept).not.toHaveBeenCalled();
    await userEvent.keyboard("s");
    expect(await screen.findByRole("heading", { name: "SWIGGY" })).toBeInTheDocument();
  });

  it("audit mode explains why confident answers are checked", async () => {
    mocked.audit!.mockResolvedValue([ITEM({ review_reason: "audit", confidence: 0.93, merchant_rows: 9 })]);
    renderReview("audit");
    expect(await screen.findByText(/Confident mistakes never reach Review/)).toBeInTheDocument();
    expect(screen.getByText(/decides 9 entries/)).toBeInTheDocument();
  });

  it("shows an error note with retry when the server is down", async () => {
    mocked.review!.mockRejectedValueOnce(new Error("Can't reach the ledger server.")).mockResolvedValueOnce([]);
    renderReview();
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the ledger server.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("All posted")).toBeInTheDocument();
  });
});

describe("page helpers", () => {
  it("describes the munim's tool calls as footnotes", () => {
    expect(describeTool({ name: "spending_summary", error: false,
      args: { start_date: "2026-07-01", end_date: "2026-07-31", group_by: "category", direction: "debit" } }))
      .toBe("spending summary · 2026-07-01 → 2026-07-31 by category (debit)");
    expect(describeTool({ name: "run_sql", args: { query: "SELECT 1" }, error: false })).toBe("read the ledger with a query");
  });

  it("marks every verified figure in a report sentence", () => {
    const { container } = render(<p><Verified text="Rent was ₹32,000, 31% of spending." /></p>);
    const nums = [...container.querySelectorAll(".verified-num")].map((n) => n.textContent);
    expect(nums).toEqual(["₹32,000", "31%"]);
  });
});
