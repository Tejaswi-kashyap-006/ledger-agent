// "The bill spike": shop bills and invoices, read by the model and pinned to the entry they explain.
// A bill never adds money to the book; the payment is already in the statement.
import { useRef, useState, type DragEvent } from "react";
import { BillSlip } from "../components/BillSlip";
import { FolioHead, Section, Sheet } from "../components/Book";
import { ErrorNote, Loading } from "../components/Controls";
import { BillIcon } from "../components/Icons";
import { Amount, Stamp } from "../components/Ledger";
import { useSlip } from "../components/Toast";
import { api } from "../lib/api";
import { day, money } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { Bill } from "../lib/types";

const ACCEPT = /\.(jpe?g|png|webp|pdf)$/i;

interface Reading { file: string; bill?: Bill; error?: string }

export function BillsPage() {
  const list = useAsync(api.bills, []);
  const [readings, setReadings] = useState<Reading[]>([]);
  const [over, setOver] = useState(false);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const slip = useSlip();

  const readAll = async (files: FileList | null) => {
    if (!files) return;
    const ok = Array.from(files).filter((f) => ACCEPT.test(f.name));
    if (ok.length < files.length) slip("Only photos and PDF invoices", "JPEG, PNG or WebP photos, or a PDF invoice.", "critical");
    if (!ok.length) return;
    setReading(true);
    for (const f of ok) {
      setReadings((r) => [{ file: f.name }, ...r]);
      try {
        const bill = await api.addBill(f);
        setReadings((r) => r.map((x) => (x.file === f.name && !x.bill && !x.error ? { ...x, bill } : x)));
        if (bill.duplicate) slip("Already on the spike", `${f.name} was read before, so it wasn't sent to the model again.`, "ink");
      } catch (e) {
        setReadings((r) => r.map((x) => (x.file === f.name && !x.bill && !x.error ? { ...x, error: (e as Error).message } : x)));
      }
    }
    setReading(false);
    list.reload();
  };

  /** Lay a bill from the spike on the desk (photo, lines, split), unless it's already there. */
  const openBill = async (id: number, filename: string) => {
    if (readings.some((r) => r.bill?.receipt_id === id)) return;
    try {
      const bill = await api.bill(id);
      setReadings((r) => [{ file: filename, bill }, ...r]);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      slip("Couldn't open that bill", (e as Error).message, "critical");
    }
  };

  const pin = async (r: Reading, transactionId: number | null) => {
    if (!r.bill) return;
    setBusy(r.bill.receipt_id);
    try {
      const bill = await api.pinBill(r.bill.receipt_id, transactionId);
      setReadings((all) => all.map((x) => (x === r ? { ...x, bill } : x)));
      slip(transactionId ? "Pinned to the entry" : "Unpinned", transactionId ? "The entry now shows what this bill was for." : undefined, "cleared");
      list.reload();
    } catch (e) {
      slip("Couldn't pin that bill", (e as Error).message, "critical");
    } finally {
      setBusy(null);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    void readAll(e.dataTransfer.files);
  };

  const aside = (
    <>
      <section>
        <p className="kicker">How a bill is posted</p>
        <ul className="notes">
          <li>The model reads the shop, the date, the total and every line, and pencils a category on each line.</li>
          <li>The book checks the lines add up to the total, then looks for an entry of exactly that amount within
            3 days. Only an exact match is pinned. Anything else waits for you.</li>
          <li>A bill never adds money to the book. The payment is already in your statement; the bill says what it was for.</li>
        </ul>
      </section>
      <section>
        <p className="kicker">What leaves your machine</p>
        <p className="small secondary">A photo goes to the model provider as it is: it can't be redacted first.
          A PDF invoice is sent as text, with phone numbers, e-mails and long account numbers masked.</p>
      </section>
    </>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Bills · evidence for entries" title="The bill spike">
        Photograph a shop bill or drop an invoice PDF. The book reads it, finds the entry it explains, and spikes it there.
      </FolioHead>

      <div className="post-form">
        <label
          className={`letterbox${over ? " is-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <input ref={input} type="file" accept="image/jpeg,image/png,image/webp,application/pdf,.pdf" multiple
            className="sr-only" disabled={reading} onChange={(e) => { void readAll(e.target.files); e.target.value = ""; }} />
          <span className="letterbox__slot" aria-hidden="true" />
          <BillIcon size={20} />
          <span className="letterbox__title">{reading ? "Reading the bill…" : "Drop bills here, or choose photos"}</span>
          <span className="small muted">JPEG, PNG or WebP photos, or PDF invoices · up to 8 MB each</span>
        </label>
      </div>

      {readings.length > 0 && (
        <Section title="On the desk" kicker="Bills">
          <div className="receipts">
            {readings.map((r, i) => r.bill ? (
              <BillSlip key={`${r.file}-${i}`} bill={r.bill} filename={r.file} busy={busy === r.bill.receipt_id}
                onPin={(id) => void pin(r, id)} onUnpin={() => void pin(r, null)} />
            ) : (
              <article key={`${r.file}-${i}`} className="receipt" aria-label={`Bill ${r.file}`}>
                <p className="receipt__head fig">{r.file}</p>
                {r.error ? (
                  <>
                    <p className="receipt__error">{r.error}</p>
                    <p className="receipt__stamp"><Stamp kind="mismatch" label="Not read" /></p>
                  </>
                ) : <p className="receipt__line"><span>Reading the bill…</span><span /></p>}
              </article>
            ))}
          </div>
        </Section>
      )}

      <Section title="On the spike" kicker="Every bill">
        {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
        {list.loading && !list.data && <Loading what="the bills" />}
        {list.data && list.data.length === 0 && <p className="muted">No bills yet. The first one you drop in appears here.</p>}
        {list.data && list.data.length > 0 && (
          <div className="table-scroll">
            <table className="ruled ledger bills-table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Shop</th>
                  <th scope="col">Pinned to</th>
                  <th scope="col" className="num">Total</th>
                </tr>
              </thead>
              <tbody className="stagger">
                {list.data.map((b) => (
                  <tr key={b.id} className={b.transaction_id == null ? "is-waiting" : ""}>
                    <td className="fig nowrap">{b.receipt_date ? day(b.receipt_date) : "-"}</td>
                    <td>
                      <button type="button" className="cat-btn ledger__payee" onClick={() => void openBill(b.id, b.filename)}
                        aria-label={`Open the bill from ${b.merchant}`}>{b.merchant}</button>
                      <span className="ledger__sub"><span className="ledger__account">{b.item_count} lines{b.items_add_up ? "" : " · don't add up"}</span></span>
                    </td>
                    <td>
                      {b.transaction_id != null
                        ? <span><span className="fig">{day(b.transaction_date ?? "")}</span> <span className="payee">{b.transaction_merchant}</span></span>
                        : <span className="muted">waiting for you</span>}
                    </td>
                    <td className="num"><Amount minor={-b.total_minor} sign="always" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && list.data.length > 0 && (
          <p className="small muted">{list.data.filter((b) => b.transaction_id != null).length} of {list.data.length} pinned ·{" "}
            {money(list.data.reduce((n, b) => n + b.total_minor, 0))} explained line by line</p>
        )}
      </Section>
    </Sheet>
  );
}
