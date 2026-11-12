// Formatting for an Indian ledger: ₹, Indian digit grouping (12,34,567), explicit signs, lakh/crore compacts.

const MINUS = "−"; // a real minus sign, not a hyphen - it aligns with "+" in figure columns

const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export type SignMode = "negative" | "always" | "never";

/** Paise -> "₹1,23,456.78". sign="always" prints "+" for money in; "never" drops the sign. */
export function money(minor: number, sign: SignMode = "negative", decimals = true): string {
  const abs = Math.abs(minor) / 100;
  const body = `₹${decimals ? inr2.format(abs) : inr0.format(Math.round(abs))}`;
  if (sign === "never" || minor === 0) return body;
  if (minor < 0) return `${MINUS}${body}`;
  return sign === "always" ? `+${body}` : body;
}

/** Whole rupees (month facts) -> "₹42,318". */
export function rupees(value: number, sign: SignMode = "negative"): string {
  return money(Math.round(value * 100), sign, false);
}

/** Compact Indian units for axes and tight spaces: ₹950, ₹45k, ₹1.2L, ₹3.4Cr. */
export function compactRupees(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? MINUS : "";
  const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, ""));
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)}L`;
  if (abs >= 1e3) return `${sign}₹${trim(abs / 1e3)}k`;
  return `${sign}₹${Math.round(abs)}`;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];

/** "2026-09" -> "September 2026" */
export function monthLong(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS[Number(m) - 1] ?? ym} ${y ?? ""}`.trim();
}

/** "2026-09" -> "September" */
export function monthName(ym: string): string {
  return MONTHS[Number(ym.split("-")[1]) - 1] ?? ym;
}

/** "2026-09" -> "Sep" */
export function monthShort(ym: string): string {
  return monthName(ym).slice(0, 3);
}

/** "2026-09-03" -> "3 Sep" (+ year when asked) */
export function day(iso: string, withYear = false): string {
  const [y, m, d] = iso.split("-");
  const mon = (MONTHS[Number(m) - 1] ?? "").slice(0, 3);
  return `${Number(d)} ${mon}${withYear ? ` ${y}` : ""}`;
}

export function pct(value: number, digits = 0, signed = false): string {
  const s = `${Math.abs(value).toFixed(digits)}%`;
  if (!signed || value === 0) return value < 0 ? `${MINUS}${s}` : s;
  return value > 0 ? `+${s}` : `${MINUS}${s}`;
}

/** "Food:Delivery" -> { group: "Food", name: "Delivery" }; "Education" -> { group: "", name: "Education" } */
export function splitCategory(category: string): { group: string; name: string } {
  const i = category.indexOf(":");
  return i < 0 ? { group: "", name: category } : { group: category.slice(0, i), name: category.slice(i + 1) };
}

/** Why an entry is in the review queue, in plain words. */
export function reasonText(reason: string | null | undefined, confidence?: number | null): string {
  switch (reason) {
    case "low_confidence":
      return confidence != null ? `The model wasn't sure (${Math.round(confidence * 100)}% confident).` : "The model wasn't sure.";
    case "suspicious_text":
      return "The narration reads like an instruction to the model. A person should decide this one.";
    case "direction_mismatch":
      return "The model's category contradicts the direction of the money.";
    case "llm_no_answer":
      return "The model didn't return an answer for this entry.";
    case "no_llm":
      return "No model is configured, so this waits for you.";
    case "sibling_of_correction":
      return "You corrected this payee elsewhere, so the model's matching answers for it are in question.";
    case "agent_proposal":
      return "The munim proposed this change while answering a question.";
    case "audit":
      return confidence != null
        ? `The model was sure (${Math.round(confidence * 100)}%). Confident mistakes never reach Review, so spot-check it.`
        : "The model was sure. Spot-check it.";
    default:
      return "Waiting for your initials.";
  }
}
