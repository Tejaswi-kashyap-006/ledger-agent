import { compactRupees, day, money, monthLong, monthShort, pct, reasonText, rupees, splitCategory } from "./format";

describe("money", () => {
  it("uses Indian digit grouping and paise", () => {
    expect(money(12345678)).toBe("₹1,23,456.78");
    expect(money(1234567890)).toBe("₹1,23,45,678.90");
    expect(money(99)).toBe("₹0.99");
  });
  it("prints a true minus sign and optional plus", () => {
    expect(money(-5050)).toBe("−₹50.50");
    expect(money(5050, "always")).toBe("+₹50.50");
    expect(money(-5050, "never")).toBe("₹50.50");
    expect(money(0, "always")).toBe("₹0.00");
  });
  it("can drop decimals", () => {
    expect(money(4231850, "never", false)).toBe("₹42,319");
    expect(rupees(145000)).toBe("₹1,45,000");
  });
});

describe("compactRupees", () => {
  it("uses thousand, lakh and crore", () => {
    expect(compactRupees(950)).toBe("₹950");
    expect(compactRupees(45000)).toBe("₹45k");
    expect(compactRupees(120000)).toBe("₹1.2L");
    expect(compactRupees(34000000)).toBe("₹3.4Cr");
    expect(compactRupees(-45000)).toBe("−₹45k");
  });
});

describe("dates and labels", () => {
  it("names months and days", () => {
    expect(monthLong("2026-09")).toBe("September 2026");
    expect(monthShort("2026-07")).toBe("Jul");
    expect(day("2026-09-03")).toBe("3 Sep");
    expect(day("2026-09-03", true)).toBe("3 Sep 2026");
  });
  it("formats percentages with signs", () => {
    expect(pct(23.1, 1, true)).toBe("+23.1%");
    expect(pct(-4, 0, true)).toBe("−4%");
    expect(pct(12)).toBe("12%");
  });
  it("splits categories", () => {
    expect(splitCategory("Food:Delivery")).toEqual({ group: "Food", name: "Delivery" });
    expect(splitCategory("Education")).toEqual({ group: "", name: "Education" });
  });
  it("explains review reasons in plain words", () => {
    expect(reasonText("low_confidence", 0.42)).toContain("42% confident");
    expect(reasonText("suspicious_text")).toContain("instruction");
    expect(reasonText("audit", 0.93)).toContain("93%");
    expect(reasonText(null)).toBe("Waiting for your initials.");
  });
});
