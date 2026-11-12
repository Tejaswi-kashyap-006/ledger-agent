// One entry at a time, as an index card laid on the page. Keyboard handling lives in the page
// (Enter / 1-9 / "/" / S); this component renders the card and exposes the same actions to the mouse.
import { forwardRef } from "react";
import { day, reasonText, splitCategory } from "../lib/format";
import type { ReviewItem } from "../lib/types";
import { CategoryPicker } from "./CategoryPicker";
import { Button } from "./Controls";
import { Amount, Highlight, Pencil, Stamp } from "./Ledger";

interface Props {
  item: ReviewItem;
  mode: "review" | "audit";
  remaining: number;
  categories: readonly string[];
  quickPicks: string[];
  busy: boolean;
  stamped: boolean;
  onAccept: () => void;
  onChoose: (category: string) => void;
  onSkip: () => void;
}

export const EntryCard = forwardRef<HTMLInputElement, Props>(function EntryCard(
  { item, mode, remaining, categories, quickPicks, busy, stamped, onAccept, onChoose, onSkip }, pickerRef,
) {
  const suggestion = item.suggestion ? splitCategory(item.suggestion) : null;
  const suspicious = item.review_reason === "suspicious_text";
  return (
    <article className={`entry-card${stamped ? " is-stamped" : ""}`} aria-labelledby={`entry-${item.id}`} aria-busy={busy}>
      <p className="kicker">
        {remaining} {mode === "audit" ? "to spot-check" : "waiting"} · {day(item.date, true)}
        {item.merchant_rows ? ` · decides ${item.merchant_rows} entries from this payee` : ""}
      </p>

      <div className="entry-card__top">
        <h2 id={`entry-${item.id}`} className="entry-card__merchant">{item.merchant || "Unknown payee"}</h2>
        <Amount minor={item.amount_minor} sign="always" className="entry-card__amount" />
      </div>
      <p className="entry-card__narration fig">{item.description}</p>

      <p className="entry-card__reason">
        {suspicious ? <Stamp kind="suspicious" size="sm" /> : mode === "audit" ? <Stamp kind="audit" size="sm" /> : null}{" "}
        <Highlight>{reasonText(item.review_reason, item.confidence)}</Highlight>
      </p>

      {suggestion && item.suggestion && (
        <div className="entry-card__suggestion">
          <p className="kicker">The model pencilled in</p>
          <p className="entry-card__guess">
            <Pencil>
              {suggestion.group && <span className="pencil__group">{suggestion.group} · </span>}
              {suggestion.name}
              {item.confidence != null && <span className="pencil__conf"> ({Math.round(item.confidence * 100)}%)</span>}
            </Pencil>
          </p>
          {item.llm_reason && <p className="entry-card__why"><Pencil>“{item.llm_reason}”</Pencil></p>}
          <Button variant="stamp" onClick={onAccept} disabled={busy || suspicious} className="entry-card__accept">
            {mode === "audit" ? "It's right, initial it" : "Initial & post"} <kbd>Enter</kbd>
          </Button>
          {suspicious && <p className="field__hint">Suspicious entries can't be accepted in one keystroke. Choose the category yourself.</p>}
        </div>
      )}

      <div className="entry-card__choose">
        <p className="kicker">{suggestion ? "Or post it under" : "Post it under"}</p>
        <ol className="quick-picks">
          {quickPicks.map((c, i) => {
            const { group, name } = splitCategory(c);
            return (
              <li key={c}>
                <button type="button" className="quick-pick" onClick={() => onChoose(c)} disabled={busy}>
                  <kbd>{i + 1}</kbd> <span className="muted">{group ? `${group} · ` : ""}</span>{name}
                </button>
              </li>
            );
          })}
        </ol>
        <CategoryPicker ref={pickerRef} categories={categories} onSelect={onChoose} label="Search every category (press /)"
          placeholder="e.g. dining, rent, fuel" />
        <div className="entry-card__foot">
          <Button variant="quiet" onClick={onSkip} disabled={busy}>Leave it for later <kbd>S</kbd></Button>
        </div>
      </div>

      <div className="entry-card__stamp" aria-hidden={!stamped}>
        {stamped && <Stamp kind="posted" pressed />}
      </div>
    </article>
  );
});
