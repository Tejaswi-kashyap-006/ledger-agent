import { render, screen } from "@testing-library/react";
import { RichText } from "./richText";

describe("RichText", () => {
  it("renders paragraphs, bold and lists", () => {
    const { container } = render(<RichText text={"You spent **₹4,210** on delivery.\n\n- Swiggy: ₹2,300\n- Zomato: ₹1,910"} />);
    expect(screen.getByText("₹4,210").tagName).toBe("STRONG");
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });

  it("never interprets HTML from model output (narrations are attacker-controlled)", () => {
    const { container } = render(<RichText text={'<img src=x onerror="alert(1)"> **hi** <script>alert(2)</script>'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("numbers ordered lists", () => {
    const { container } = render(<RichText text={"1. first\n2. second"} />);
    expect(container.querySelector("ol")).not.toBeNull();
  });
});
