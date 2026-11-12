// "The ledger": every entry, ruled, filterable. Categories show who decided them (pencil / RULE / You),
// and any category can be corrected in place - which feeds the same learning loop as Review.
import { useEffect, useState } from "react";
import { FolioHead, Sheet } from "../components/Book";
import { CategoryPicker } from "../components/CategoryPicker";
import { Button, ErrorNote, Loading, SelectField, TextField } from "../components/Controls";
import { Amount, CategoryLabel, Highlight, Pencil, Stamp } from "../components/Ledger";
import { useSlip } from "../components/Toast";
import { api } from "../lib/api";
import { day, monthLong } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { TxnQuery } from "../lib/types";

const PAGE = 40;

export function LedgerPage() {
  const months = useAsync(api.months, []);
  const categories = useAsync(api.categories, []);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState<TxnQuery>({ limit: PAGE, offset: 0 });
  const page = useAsync(() => api.transactions(q), [JSON.stringify(q)]);
  const [editing, setEditing] = useState<number | null>(null);
  const slip = useSlip();

  // search as you type, lightly debounced
  useEffect(() => {
    const t = setTimeout(() => setQ((prev) => ({ ...prev, q: search || undefined, offset: 0 })), 250);
    return () => clearTimeout(t);
  }, [search]);

  const set = (patch: Partial<TxnQuery>) => setQ((prev) => ({ ...prev, ...patch, offset: 0 }));

  const recategorise = async (id: number, category: string) => {
    setEditing(null);
    try {
      const r = await api.setCategory(id, category);
      slip(r.rule_created ? "Corrected — and a rule was learned" : "Corrected",
        r.propagated ? `${r.propagated} more entries from this payee were posted with it.`
          : r.siblings_flagged ? `${r.siblings_flagged} of the model's matching answers for this payee went back to Review.` : undefined,
        "cleared");
      page.reload();
    } catch (e) {
      slip("Couldn't change that entry", (e as Error).message, "critical");
    }
  };

  const total = page.data?.total ?? 0;
  const offset = q.offset ?? 0;
  const folio = Math.floor(offset / PAGE) + 1;
  const folios = Math.max(1, Math.ceil(total / PAGE));

  const aside = (
    <section>
      <p className="kicker">Reading the ledger</p>
      <ul className="legend-notes">
        <li><Pencil>Food · Delivery</Pencil><span className="small secondary">pencilled by the model</span></li>
        <li><span>Food · Delivery <Stamp kind="rule" size="sm" /></span><span className="small secondary">posted by a rule</span></li>
        <li><span>Food · Delivery <Stamp kind="verified" size="sm" label="You" /></span><span className="small secondary">decided by you</span></li>
        <li><Highlight>Awaiting initials</Highlight><span className="small secondary">in the review queue</span></li>
      </ul>
      <p className="small muted">Select a category to correct it. A correction teaches the book exactly like Review does.</p>
    </section>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Ledger · every entry" title="The ledger" />

      <div className="filters" role="search">
        <TextField label="Search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="payee or narration" />
        <SelectField label="Month" value={q.month ?? ""} onChange={(e) => set({ month: e.target.value || undefined })}>
          <option value="">All months</option>
          {months.data?.map((m) => <option key={m} value={m}>{monthLong(m)}</option>)}
        </SelectField>
        <SelectField label="Status" value={q.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
          <option value="">Any</option>
          <option value="needs_review">Awaiting initials</option>
          <option value="categorized">Posted</option>
          <option value="pending">Not yet processed</option>
        </SelectField>
        <SelectField label="Category" value={q.category ?? ""} onChange={(e) => set({ category: e.target.value || undefined })}>
          <option value="">Any</option>
          {categories.data?.map((c) => <option key={c} value={c}>{c.replace(":", " · ")}</option>)}
        </SelectField>
      </div>

      {page.error && <ErrorNote error={page.error} onRetry={page.reload} />}
      {page.loading && !page.data && <Loading what="the ledger" />}
      {page.data && (
        <>
          <p className="kicker">{total} {total === 1 ? "entry" : "entries"} · folio {folio} of {folios}</p>
          <div className="table-scroll">
            <table className="ruled ledger">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Payee &amp; narration</th>
                  <th scope="col">Category</th>
                  <th scope="col" className="num">Amount</th>
                </tr>
              </thead>
              <tbody className="stagger">
                {page.data.items.map((t) => (
                  <tr key={t.id} className={t.status === "needs_review" ? "is-waiting" : ""}>
                    <td className="fig nowrap">{day(t.date)}</td>
                    <td>
                      <span className="ledger__payee">{t.merchant || "-"}</span>
                      <span className="ledger__sub">
                        <span className="ledger__narration fig" title={t.description}>{t.description}</span>
                        <span className="ledger__account">{t.account}</span>
                      </span>
                    </td>
                    <td className="ledger__cat">
                      {editing === t.id && categories.data ? (
                        <div className="inline-picker">
                          <CategoryPicker categories={categories.data} onSelect={(c) => recategorise(t.id, c)} autoFocus
                            hideLabel label={`New category for ${t.merchant}`} />
                          <Button variant="quiet" onClick={() => setEditing(null)}>Cancel</Button>
                        </div>
                      ) : (
                        <button type="button" className="cat-btn" onClick={() => setEditing(t.id)}
                          aria-label={`Change category for ${t.merchant || "this entry"}, currently ${t.category ?? "not posted"}`}>
                          {t.status === "needs_review" ? <Highlight><CategoryLabel category={t.category} source={t.category_source} /></Highlight>
                            : <CategoryLabel category={t.category} source={t.category_source} />}
                        </button>
                      )}
                    </td>
                    <td className="num"><Amount minor={t.amount_minor} sign="always" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page.data.items.length === 0 && <p className="muted">No entries match. Loosen a filter.</p>}
          <nav className="pager" aria-label="Folios">
            <Button variant="quiet" disabled={offset === 0} onClick={() => setQ((p) => ({ ...p, offset: Math.max(0, offset - PAGE) }))}>
              ← Previous folio
            </Button>
            <span className="fig small muted">{folio} / {folios}</span>
            <Button variant="quiet" disabled={offset + PAGE >= total} onClick={() => setQ((p) => ({ ...p, offset: offset + PAGE }))}>
              Next folio →
            </Button>
          </nav>
        </>
      )}
    </Sheet>
  );
}
