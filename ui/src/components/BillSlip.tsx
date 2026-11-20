// A shop bill, as the model read it, laid on the page like the import receipts (same slip, same torn edge).
// What the model read is provisional, so its categories are pencilled; what code checked (the items add up,
// the amount matches an entry to the paisa) is stamped.
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { day, money, splitCategory } from "../lib/format";
import type { Bill, BillItem } from "../lib/types";
import { Button } from "./Controls";
import { AlertIcon, TickIcon } from "./Icons";
import { Amount, Highlight, Pencil, Stamp } from "./Ledger";

/** Line items grouped by category: the split a bank statement can't show. Largest first. */
export function splitByCategory(items: BillItem[]): { category: string; amount_minor: number }[] {
  const sums = new Map<string, number>();
  for (const i of items) sums.set(i.category, (sums.get(i.category) ?? 0) + i.amount_minor);
  return [...sums].map(([category, amount_minor]) => ({ category, amount_minor }))
    .filter((s) => s.amount_minor !== 0)
    .sort((a, b) => b.amount_minor - a.amount_minor);
}

function CategoryPencil({ category }: { category: string }) {
  const { group, name } = splitCategory(category);
  return <Pencil className="bill__cat">{group && <span className="pencil__group">{group} · </span>}{name}</Pencil>;
}

/** The split, compact: used on the review card as evidence. */
export function BillSplit({ bill }: { bill: Bill }) {
  const split = splitByCategory(bill.items);
  return (
    <ul className="bill-split" aria-label={`What the bill from ${bill.merchant} was for`}>
      {split.map((s) => (
        <li key={s.category}><CategoryPencil category={s.category} /><span className="fig">{money(s.amount_minor)}</span></li>
      ))}
    </ul>
  );
}

/** The stored photo or invoice. Fetched with the bearer token, shown from an object URL. */
export function BillFile({ id, mime, merchant }: { id: number; mime: "image" | "pdf"; merchant: string }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    let live = true;
    let made: string | undefined;
    api.billFile(id).then((b) => {
      if (!live) return;
      made = URL.createObjectURL(b);
      setUrl(made);
    }, () => {});
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [id]);
  if (!url) return null;
  return mime === "pdf"
    ? <a className="small" href={url} target="_blank" rel="noreferrer">Open the invoice PDF</a>
    : <img className="bill__photo" src={url} alt={`Photo of the bill from ${merchant}`} />;
}

interface SlipProps {
  bill: Bill;
  filename: string;
  onPin?: (transactionId: number) => void;
  onUnpin?: () => void;
  busy?: boolean;
}

export function BillSlip({ bill, filename, onPin, onUnpin, busy }: SlipProps) {
  const itemsTotal = bill.items.reduce((n, i) => n + i.amount_minor, 0);
  const split = splitByCategory(bill.items);
  const pinned = bill.transaction_id != null;
  return (
    <article className="receipt bill" aria-label={`Bill from ${bill.merchant}`}>
      <p className="receipt__head">
        <span className="bill__merchant">{bill.merchant}</span>
        <span className="small muted">{bill.receipt_date ? day(bill.receipt_date, true) : "no date printed"} · {filename}</span>
      </p>
      <BillFile id={bill.receipt_id} mime={/\.pdf$/i.test(filename) ? "pdf" : "image"} merchant={bill.merchant} />

      <ul className="bill__items">
        {bill.items.map((i, n) => (
          <li key={n} className="receipt__line"><span>{i.description}</span><span>{money(i.amount_minor)}</span></li>
        ))}
      </ul>
      <p className="receipt__rule" aria-hidden="true" />
      <p className="receipt__line bill__total"><span>Total paid</span><strong>{money(bill.total_minor)}</strong></p>
      <p className={`bill__check ${bill.items_add_up ? "is-ok" : ""}`}>
        {bill.items_add_up
          ? <><TickIcon size={12} /> The items add up to the total</>
          : <><AlertIcon size={12} /> <Highlight>The items come to {money(itemsTotal)}, not {money(bill.total_minor)}. Check the photo.</Highlight></>}
      </p>

      {split.length > 1 && (
        <>
          <p className="kicker">One payment, {split.length} kinds of spending</p>
          <ul className="bill-split">
            {split.map((s) => (
              <li key={s.category}><CategoryPencil category={s.category} /><span className="fig">{money(s.amount_minor)}</span></li>
            ))}
          </ul>
        </>
      )}

      {pinned ? (
        <div className="bill__pin">
          <p className="receipt__stamp"><Stamp kind="pinned" label={bill.match_status === "user" ? "Pinned by you" : "Pinned to entry"} /></p>
          {onUnpin && <Button variant="quiet" onClick={onUnpin} disabled={busy}>Unpin</Button>}
        </div>
      ) : (
        <div className="bill__unpinned">
          <p><Highlight>No entry of exactly {money(bill.total_minor)} within 3 days{bill.receipt_date ? ` of ${day(bill.receipt_date)}` : ""}.</Highlight></p>
          {bill.candidates.length > 0 ? (
            <>
              <p className="kicker">Pin it to one of these</p>
              <ul className="bill__candidates">
                {bill.candidates.map((c) => (
                  <li key={c.id}>
                    <button type="button" className="quick-pick" disabled={busy} onClick={() => onPin?.(c.id)}>
                      <span className="fig">{day(c.date)}</span> <span className="payee">{c.merchant || c.description.slice(0, 24)}</span>{" "}
                      <Amount minor={c.amount_minor} sign="always" /> <span className="small muted">{c.account}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : <p className="small muted">Nothing close in the book yet. Import that month's statement, then pin it.</p>}
        </div>
      )}
    </article>
  );
}

/** On the review card: what the pinned bill says the payment was for. */
export function BillEvidence({ id }: { id: number }) {
  const [bill, setBill] = useState<Bill>();
  useEffect(() => {
    let live = true;
    api.bill(id).then((b) => { if (live) setBill(b); }, () => {});
    return () => { live = false; };
  }, [id]);
  if (!bill) return null;
  return (
    <div className="entry-card__bill">
      <p className="kicker">The bill from {bill.merchant} says</p>
      <BillSplit bill={bill} />
    </div>
  );
}
