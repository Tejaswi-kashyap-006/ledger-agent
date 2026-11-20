import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { BillSlip, splitByCategory } from "../components/BillSlip";
import { SlipProvider } from "../components/Toast";
import type { Bill } from "../lib/types";

vi.mock("../lib/api", async (orig) => {
  const actual = await orig<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      bills: vi.fn(async () => []),
      addBill: vi.fn(),
      pinBill: vi.fn(),
      billFile: vi.fn(async () => new Blob(["x"], { type: "image/png" })),
      bill: vi.fn(),
      accounts: vi.fn(async () => []),
      importFile: vi.fn(),
    },
  };
});

import { api } from "../lib/api";
import { BillsPage } from "./Bills";
import { PostStatementPage } from "./PostStatement";

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const BILL = (over: Partial<Bill> = {}): Bill => ({
  receipt_id: 3, merchant: "Apollo Pharmacy", receipt_date: "2026-08-16", total_minor: 89000,
  items: [
    { description: "Dolo 650mg Tablet 15s", amount_minor: 3400, category: "Health:Pharmacy" },
    { description: "Volini Pain Relief Gel 30g", amount_minor: 52700, category: "Health:Pharmacy" },
    { description: "Himalaya Neem Face Wash 150ml", amount_minor: 32900, category: "Personal Care" },
  ],
  items_add_up: true, match_status: "matched", transaction_id: 41, duplicate: false, candidates: [], ...over,
});

function wrap(ui: React.ReactNode) {
  return render(<MemoryRouter><SlipProvider>{ui}</SlipProvider></MemoryRouter>);
}

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => "blob:bill");
  URL.revokeObjectURL = vi.fn();
});
beforeEach(() => vi.clearAllMocks());

describe("BillSlip", () => {
  it("splits one payment by category, largest first", () => {
    expect(splitByCategory(BILL().items)).toEqual([
      { category: "Health:Pharmacy", amount_minor: 56100 },
      { category: "Personal Care", amount_minor: 32900 },
    ]);
  });

  it("shows the lines, the split and the pin stamp", async () => {
    wrap(<BillSlip bill={BILL()} filename="apollo.png" />);
    expect(screen.getByText("Volini Pain Relief Gel 30g")).toBeInTheDocument();
    expect(screen.getByText("One payment, 2 kinds of spending")).toBeInTheDocument();
    expect(screen.getByText("The items add up to the total")).toBeInTheDocument();
    expect(screen.getByText("Pinned to entry")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Photo of the bill from Apollo Pharmacy" })).toHaveAttribute("src", "blob:bill");
  });

  it("warns when the lines don't add up, and offers entries to pin an unmatched bill to", async () => {
    const onPin = vi.fn();
    wrap(<BillSlip filename="a.png" onPin={onPin} bill={BILL({
      total_minor: 95000, items_add_up: false, transaction_id: null, match_status: "unmatched",
      candidates: [{ id: 9, date: "2026-08-17", amount_minor: -89500, merchant: "APOLLO PHARMACY", description: "UPI",
        account: "HDFC Savings", name_overlap: 2 }],
    })} />);
    expect(screen.getByText("The items come to ₹890.00, not ₹950.00. Check the photo.")).toBeInTheDocument();
    expect(screen.getByText("No entry of exactly ₹950.00 within 3 days of 16 Aug.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /APOLLO PHARMACY/ }));
    expect(onPin).toHaveBeenCalledWith(9);
  });
});

describe("Bills page", () => {
  it("reads a dropped photo and shows where it was pinned", async () => {
    mocked.addBill!.mockResolvedValue(BILL());
    wrap(<BillsPage />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["png"], "apollo.png", { type: "image/png" }));
    await waitFor(() => expect(mocked.addBill).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Pinned to entry")).toBeInTheDocument();
    expect(mocked.bills).toHaveBeenCalledTimes(2);                 // the spike is re-read after a bill is added
  });

  it("opens a bill from the spike onto the desk", async () => {
    mocked.bills!.mockResolvedValue([{ id: 3, filename: "apollo.png", merchant: "Apollo Pharmacy", receipt_date: "2026-08-16",
      total_minor: 89000, match_status: "matched", transaction_id: 41, created_at: "", item_count: 3, items_add_up: 1,
      transaction_date: "2026-08-16", transaction_merchant: "APOLLO PHARMACY" }]);
    mocked.bill!.mockResolvedValue(BILL());
    wrap(<BillsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Open the bill from Apollo Pharmacy" }));
    expect(mocked.bill).toHaveBeenCalledWith(3);
    expect(await screen.findByText("One payment, 2 kinds of spending")).toBeInTheDocument();
  });

  it("shows the model's refusal on the slip", async () => {
    mocked.addBill!.mockRejectedValue(new Error("That doesn't look like a receipt or invoice"));
    wrap(<BillsPage />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["png"], "cat.png", { type: "image/png" }));
    expect(await screen.findByText(/doesn't look like a receipt/)).toBeInTheDocument();
    expect(screen.getByText("Not read")).toBeInTheDocument();
  });
});

describe("Import", () => {
  it("asks for a password only when a PDF is chosen, and sends it with the PDF", async () => {
    mocked.importFile!.mockResolvedValue({ import_id: 1, account: "HDFC Savings", profile_name: "heuristic", rows_total: 28,
      rows_new: 28, rows_duplicate: 0, rows_rejected: 0, balance_check: "ok", balance_mismatches: 0, rejects: [] });
    wrap(<PostStatementPage />);
    expect(screen.queryByLabelText(/PDF password/)).not.toBeInTheDocument();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["%PDF-1.4"], "sept.pdf", { type: "application/pdf" }));
    await userEvent.type(screen.getByLabelText(/PDF password/), "SHAR0101");
    await userEvent.type(screen.getByLabelText("Account"), "HDFC Savings");
    await userEvent.click(screen.getByRole("button", { name: "Post statement" }));
    await waitFor(() => expect(mocked.importFile).toHaveBeenCalledWith("HDFC Savings", expect.any(File), "SHAR0101"));
    expect(await screen.findByText("Reconciled")).toBeInTheDocument();
  });
});
