// Ledger primitives: Amount, Stamp, Pencil, Highlight, CategoryLabel, HeroFigure.
// These encode DESIGN.md's trust system: model = blue pencil, rule = RULE stamp, you = black ink + tick.
import type { ReactNode } from "react";
import { money, rupees, splitCategory, type SignMode } from "../lib/format";
import type { CategorySource } from "../lib/types";
import { AlertIcon, CrossIcon, EyeIcon, PencilIcon, RuleIcon, ScaleIcon, TickIcon } from "./Icons";

export function Amount({ minor, sign = "negative", className = "" }: { minor: number; sign?: SignMode; className?: string }) {
  const dir = minor < 0 ? "out" : minor > 0 ? "in" : "zero";
  return (
    <span className={`amt amt--${dir} ${className}`} aria-label={`${minor < 0 ? "money out " : minor > 0 ? "money in " : ""}${money(minor, "never")}`}>
      {money(minor, sign)}
    </span>
  );
}

export function Rupees({ value, sign }: { value: number; sign?: SignMode }) {
  return <span className="amt">{rupees(value, sign)}</span>;
}

export type StampKind = "reconciled" | "mismatch" | "rule" | "verified" | "suspicious" | "posted" | "audit" | "unchecked";

const STAMPS: Record<StampKind, { label: string; icon: ReactNode; tone: string }> = {
  reconciled: { label: "Reconciled", icon: <ScaleIcon size={14} />, tone: "cleared" },
  mismatch: { label: "Balance mismatch", icon: <AlertIcon size={14} />, tone: "critical" },
  rule: { label: "Rule", icon: <RuleIcon size={12} />, tone: "ink" },
  verified: { label: "Verified", icon: <TickIcon size={12} />, tone: "ink" },
  suspicious: { label: "Suspicious", icon: <AlertIcon size={14} />, tone: "critical" },
  posted: { label: "Posted", icon: <TickIcon size={14} />, tone: "cleared" },
  audit: { label: "Audit", icon: <EyeIcon size={14} />, tone: "pencil" },
  unchecked: { label: "No balance column", icon: <CrossIcon size={12} />, tone: "muted" },
};

/** A rubber stamp. `size="sm"` is the flat inline version used in tables. */
export function Stamp({ kind, size = "lg", label, pressed = false }: { kind: StampKind; size?: "sm" | "lg"; label?: string; pressed?: boolean }) {
  const s = STAMPS[kind];
  return (
    <span className={`stamp stamp--${size} stamp--${s.tone}${pressed ? " is-pressed" : ""}`}>
      {s.icon}
      <span>{label ?? s.label}</span>
    </span>
  );
}

/** Model-written text: blue pencil in the margin. Provisional by design. */
export function Pencil({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`pencil ${className}`}>{children}</span>;
}

/** The haldi highlighter swipe: a person should look at this. */
export function Highlight({ children }: { children: ReactNode }) {
  return <mark className="highlight">{children}</mark>;
}

/** A category as written in the ledger: pencil if the model wrote it, ink + stamp if a rule or a person did. */
export function CategoryLabel({ category, source }: { category: string | null; source: CategorySource }) {
  if (!category) return <span className="muted">Not yet posted</span>;
  const { group, name } = splitCategory(category);
  const text = (
    <>
      {group && <span className="cat__group">{group} · </span>}
      <span className="cat__name">{name}</span>
    </>
  );
  if (source === "llm") {
    return (
      <span className="cat cat--pencil" title="Suggested by the model">
        <PencilIcon size={12} /> {text}
      </span>
    );
  }
  return (
    <span className="cat">
      {text} {source === "rule" ? <Stamp kind="rule" size="sm" /> : source === "user" ? <Stamp kind="verified" size="sm" label="You" /> : null}
    </span>
  );
}

/** The one hero figure per view (Rozha One, crosses the margin rule). */
export function HeroFigure({ label, value, note }: { label: string; value: string; note?: ReactNode }) {
  return (
    <div className="hero ink-in">
      <p className="kicker hero__label">{label}</p>
      <p className="hero__value display">{value}</p>
      {note && <p className="hero__note">{note}</p>}
    </div>
  );
}
