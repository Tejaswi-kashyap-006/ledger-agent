import { LINE, snapExtra } from "./rhythm";

describe("snapExtra (vertical rhythm)", () => {
  it("rounds a block up to whole ruled lines", () => {
    expect(snapExtra(42)).toBe(14);          // a 42px button occupies 2 lines
    expect(snapExtra(150)).toBe(18);         // a 150px card occupies 6 lines
    expect(snapExtra(LINE)).toBe(0);
    expect(snapExtra(LINE * 3)).toBe(0);
  });
  it("tolerates sub-pixel noise instead of adding a whole extra line", () => {
    expect(snapExtra(56.3)).toBe(0);
    expect(snapExtra(55.8)).toBeCloseTo(0.2, 2);
  });
  it("leaves empty blocks alone", () => {
    expect(snapExtra(0)).toBe(0);
  });
});
