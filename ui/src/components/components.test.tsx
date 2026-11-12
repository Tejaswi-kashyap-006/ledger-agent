import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { CategoryPicker, matchCategories } from "./CategoryPicker";
import { InOutTrend } from "./charts/InOutTrend";
import { RuledBars } from "./charts/RuledBars";
import { Amount, CategoryLabel } from "./Ledger";

const CATS = ["Food:Groceries", "Food:Delivery", "Food:Dining Out", "Housing:Rent", "Transfers:To People"];

describe("CategoryPicker", () => {
  it("matches every typed word", () => {
    expect(matchCategories(CATS, "food del")).toEqual(["Food:Delivery"]);
    expect(matchCategories(CATS, "")).toHaveLength(5);
    expect(matchCategories(CATS, "zzz")).toEqual([]);
  });

  it("is fully keyboard operable", async () => {
    const onSelect = vi.fn();
    render(<CategoryPicker categories={CATS} onSelect={onSelect} />);
    const box = screen.getByRole("combobox");
    await userEvent.click(box);
    await userEvent.type(box, "food");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onSelect).toHaveBeenCalledWith("Food:Delivery");
    expect(box).toHaveValue("");
  });

  it("says when nothing matches and closes on Escape", async () => {
    render(<CategoryPicker categories={CATS} onSelect={() => {}} />);
    const box = screen.getByRole("combobox");
    await userEvent.type(box, "crypto");
    expect(screen.getByText(/No category matches/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });
});

describe("ledger primitives", () => {
  it("Amount signs and labels direction for screen readers", () => {
    render(<><Amount minor={-45000} /><Amount minor={145000} sign="always" /></>);
    expect(screen.getByLabelText("money out ₹450.00")).toHaveTextContent("−₹450.00");
    expect(screen.getByLabelText("money in ₹1,450.00")).toHaveTextContent("+₹1,450.00");
  });

  it("CategoryLabel shows who decided", () => {
    const { rerender, container } = render(<CategoryLabel category="Food:Delivery" source="llm" />);
    expect(container.querySelector(".cat--pencil")).not.toBeNull();
    rerender(<CategoryLabel category="Food:Delivery" source="rule" />);
    expect(screen.getByText("Rule")).toBeInTheDocument();
    rerender(<CategoryLabel category="Food:Delivery" source="user" />);
    expect(screen.getByText("You")).toBeInTheDocument();
    rerender(<CategoryLabel category={null} source={null} />);
    expect(screen.getByText("Not yet posted")).toBeInTheDocument();
  });
});

describe("charts", () => {
  const trend = [
    { month: "2026-06", money_in: 14500000, money_out: 9800000, unreviewed: 0 },
    { month: "2026-07", money_in: 14500000, money_out: 10400000, unreviewed: 2 },
  ];

  it("InOutTrend has a legend, direct end labels and a table view", async () => {
    render(<InOutTrend data={trend} />);
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("Money in");
    expect(screen.getByText("In ₹1.4L")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as table" }));
    expect(screen.getByRole("table")).toHaveTextContent("July 2026");
    expect(screen.getByRole("table")).toHaveTextContent("₹1,04,000");
  });

  it("InOutTrend is readable with the keyboard", () => {
    render(<InOutTrend data={trend} />);
    const svg = screen.getByRole("img");
    fireEvent.keyDown(svg, { key: "ArrowRight" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("June 2026");
    expect(screen.getByRole("tooltip")).toHaveTextContent("₹98,000");
  });

  it("RuledBars is a real table with values at the bar tips", () => {
    render(<RuledBars caption="Spending" data={[{ label: "Housing:Rent", value: 32000, share: 31 }, { label: "Food:Delivery", value: 4210 }]} />);
    const table = screen.getByRole("table", { name: "Spending" });
    expect(table).toHaveTextContent("Rent");
    expect(table).toHaveTextContent("₹32,000");
    expect(table).toHaveTextContent("31% of spending");
  });
});
