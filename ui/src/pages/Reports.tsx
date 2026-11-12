// "Monthly folio": an editorial write-up whose every number is checked against the books.
// Verified figures carry a small tick; sentences the verifier removed appear under "Struck from the record".
import { Fragment, useEffect, useState } from "react";
import { FolioHead, Section, Sheet } from "../components/Book";
import { RuledBars } from "../components/charts/RuledBars";
import { Button, ErrorNote, Loading } from "../components/Controls";
import { TickIcon } from "../components/Icons";
import { Rupees, Stamp } from "../components/Ledger";
import { api } from "../lib/api";
import { monthLong, monthName, monthShort } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { Report } from "../lib/types";

/** Every figure left in a published sentence passed the verifier - mark it. */
export function Verified({ text }: { text: string }) {
  // a figure must END on a digit, so "₹32,000," keeps its clause comma outside the mark
  const parts = text.split(/(₹?\d(?:[\d,]*\d)?(?:\.\d+)?%?)/g);
  return (
    <>
      {parts.map((p, i) => (/\d/.test(p)
        ? <span key={i} className="verified-num fig">{p}<TickIcon size={10} aria-hidden="true" /></span>
        : <Fragment key={i}>{p}</Fragment>))}
    </>
  );
}

export function ReportsPage() {
  const months = useAsync(api.months, []);
  const [month, setMonth] = useState<string>();
  useEffect(() => { if (!month && months.data?.length) setMonth(months.data[0]); }, [months.data, month]);
  const facts = useAsync(() => (month ? api.facts(month) : Promise.resolve(undefined)), [month]);
  const [report, setReport] = useState<Report>();
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<Error>();

  useEffect(() => { setReport(undefined); setError(undefined); }, [month]);

  const write = async () => {
    if (!month) return;
    setWriting(true);
    setError(undefined);
    try {
      setReport(await api.report(month));
    } catch (e) {
      setError(e as Error);
    } finally {
      setWriting(false);
    }
  };

  const f = report?.facts ?? facts.data;
  const n = report?.narrative;

  const aside = (
    <section>
      <p className="kicker">How the figures are kept honest</p>
      <p className="small secondary">The totals are computed from the ledger. The model only writes the sentences, and it's told to
        use those figures alone. Every number in its draft is then checked against the books. A draft that invents a number is
        sent back, and a sentence that still doesn't match is struck out before you see it.</p>
      {report && (
        <p className="small"><Stamp kind="verified" size="sm" label={`${report.attempts} ${report.attempts === 1 ? "draft" : "drafts"} checked`} /></p>
      )}
    </section>
  );

  if (months.loading) return <Sheet><Loading what="the folios" /></Sheet>;
  if (months.error) return <Sheet><ErrorNote error={months.error} onRetry={months.reload} /></Sheet>;
  if (!months.data?.length || !month) {
    return <Sheet><FolioHead kicker="Reports" title="No folios yet">Post a statement first. Reports are written per month.</FolioHead></Sheet>;
  }

  return (
    <Sheet aside={aside}>
      <FolioHead kicker={`Reports · ${monthLong(month)}`} title={n ? n.headline : `The ${monthName(month)} folio`} />
      <nav className="month-tabs" aria-label="Choose a month">
        {months.data.slice(0, 12).map((m) => (
          <button key={m} type="button" className="month-tab" aria-pressed={m === month} onClick={() => setMonth(m)}>
            {monthShort(m)} <span className="fig">{m.slice(2, 4)}</span>
          </button>
        ))}
      </nav>

      {!report && (
        <div className="write-cta">
          <p className="secondary">The figures below are ready. Ask the model to write them up as a short folio: highlights,
            things to watch, and a few suggestions.</p>
          <Button onClick={write} disabled={writing}>{writing ? "Writing and checking…" : `Write the ${monthName(month)} folio`}</Button>
          {error && (
            <p className="note note--error" role="alert">
              {error.message.includes("OPENAI") || error.message.includes("unavailable")
                ? "No language model is configured, so there's no write-up. The figures below are complete on their own."
                : error.message}
            </p>
          )}
        </div>
      )}

      {report && !n && <p className="note">No language model is configured, so there's no write-up. The figures below are complete on their own.</p>}

      {n && (
        <div className="editorial ink-in">
          {n.highlights.map((h, i) => <p key={i} className={i === 0 ? "editorial__lede" : ""}><Verified text={h} /></p>)}
          {n.watch_outs.length > 0 && (
            <>
              <h2 className="h-section">Watch out</h2>
              <ul className="editorial__list">{n.watch_outs.map((w, i) => <li key={i}><Verified text={w} /></li>)}</ul>
            </>
          )}
          {n.suggestions.length > 0 && (
            <>
              <h2 className="h-section">Suggestions</h2>
              <ul className="editorial__list">{n.suggestions.map((s, i) => <li key={i}><Verified text={s} /></li>)}</ul>
            </>
          )}
          {report.removed_sentences.length > 0 && (
            <div className="struck">
              <p className="kicker">Struck from the record</p>
              <p className="small muted">These sentences quoted figures that don't appear in your books, so they were removed:</p>
              <ul>{report.removed_sentences.map((s, i) => <li key={i}><del>{s}</del></li>)}</ul>
            </div>
          )}
        </div>
      )}

      {facts.error && <ErrorNote error={facts.error} onRetry={facts.reload} />}
      {f && (
        <>
          <div className="jama-naam">
            <div className="jama-naam__col"><p className="kicker">Jama · money in</p><p className="jama-naam__figure"><Rupees value={f.income} /></p></div>
            <div className="jama-naam__col"><p className="kicker">Naam · money out</p><p className="jama-naam__figure"><Rupees value={f.expenses} /></p></div>
            <div className="jama-naam__col"><p className="kicker">Kept</p><p className="jama-naam__figure"><Rupees value={f.net_savings} /></p>
              {f.savings_rate_pct != null && <p className="small muted">{f.savings_rate_pct}% of income</p>}</div>
          </div>
          <Section title="Where the money went" kicker="By category">
            <RuledBars data={f.top_categories.map((c) => ({ label: c.category, value: c.amount, share: c.share_pct }))}
              caption={`Spending by category, ${monthLong(month)}`} />
          </Section>
          {f.unreviewed_transactions > 0 && (
            <p className="small muted">{f.unreviewed_transactions} entries this month still await review, so these totals may change.</p>
          )}
        </>
      )}
    </Sheet>
  );
}
