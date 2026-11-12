// "{Month} folio": the month at a glance. Hero net figure, Jama · Naam, where it went, and the margin notes.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FolioHead, Section, Sheet } from "../components/Book";
import { InOutTrend } from "../components/charts/InOutTrend";
import { RuledBars } from "../components/charts/RuledBars";
import { Button, ErrorNote, Loading } from "../components/Controls";
import { ArrowDownIcon, ArrowUpIcon } from "../components/Icons";
import { Highlight, HeroFigure, Rupees } from "../components/Ledger";
import { useSlip } from "../components/Toast";
import { api } from "../lib/api";
import { monthLong, monthName, monthShort, pct, rupees } from "../lib/format";
import { useAsync } from "../lib/hooks";

export function FolioPage() {
  const months = useAsync(api.months, []);
  const [month, setMonth] = useState<string>();
  useEffect(() => { if (!month && months.data?.length) setMonth(months.data[0]); }, [months.data, month]);

  if (months.loading) return <Sheet><Loading what="this month's folio" /></Sheet>;
  if (months.error) return <Sheet><ErrorNote error={months.error} onRetry={months.reload} /></Sheet>;
  if (!months.data?.length || !month) return <EmptyBook />;
  return <Folio month={month} months={months.data} onMonth={setMonth} />;
}

function EmptyBook() {
  return (
    <Sheet aside={<section><p className="kicker">Trying it out?</p><p className="secondary">Run <code className="fig">ledger demo</code> for
      three months of realistic sample statements from two accounts, then post them here.</p></section>}>
      <FolioHead kicker="A new book" title="Nothing posted yet">
        Every bahi-khata starts with a blank page. Post a bank or card statement and the book fills itself in:
        categorised, de-duplicated and checked against the running balance.
      </FolioHead>
      <p><Link className="btn btn--ink" to="/import">Post your first statement</Link></p>
    </Sheet>
  );
}

function Folio({ month, months, onMonth }: { month: string; months: string[]; onMonth: (m: string) => void }) {
  const facts = useAsync(() => api.facts(month), [month]);
  const trend = useAsync(api.trend, []);
  const stats = useAsync(api.stats, []);
  const slip = useSlip();
  const [processing, setProcessing] = useState(false);

  const processNow = async () => {
    setProcessing(true);
    try {
      const r = await api.process();
      const s = r.stats;
      slip(`Posted ${s.processed - s.to_review} of ${s.processed} entries`,
        `${s.by_rule} by your rules · ${s.by_llm} by the model · ${s.to_review} waiting for you`, "cleared");
      facts.reload(); stats.reload(); trend.reload();
    } catch (e) {
      slip("Processing stopped", (e as Error).message, "critical");
    } finally {
      setProcessing(false);
    }
  };

  const f = facts.data;
  const s = stats.data;
  const pending = s?.by_status.pending ?? 0;

  const aside = (
    <>
      {s && s.review_backlog > 0 && (
        <section className="attention">
          <p className="kicker">Waiting for you</p>
          <p className="attention__line"><Highlight>{s.review_backlog} {s.review_backlog === 1 ? "entry awaits" : "entries await"} your initials</Highlight></p>
          <Link to="/review" className="link-arrow">Open review</Link>
        </section>
      )}
      {trend.data && <section><InOutTrend data={trend.data} /></section>}
      {s && (
        <section>
          <p className="kicker">Posted without you</p>
          <p className="stat-line"><span className="display stat-line__big">{Math.round(s.automation_rate * 100)}%</span><span>of {s.transactions} entries</span></p>
          <ul className="tally">
            <li><span>by your rules</span><span className="fig">{s.categorized_by.rule ?? 0}</span></li>
            <li><span>by the model</span><span className="fig">{s.categorized_by.llm ?? 0}</span></li>
            <li><span>by you</span><span className="fig">{s.categorized_by.user ?? 0}</span></li>
          </ul>
          <p className="small muted">{s.rules.compiled} {s.rules.compiled === 1 ? "rule" : "rules"} learned from your corrections so far.</p>
          {pending > 0 && (
            <Button onClick={processNow} disabled={processing}>
              {processing ? "Posting…" : `Post ${pending} pending ${pending === 1 ? "entry" : "entries"}`}
            </Button>
          )}
        </section>
      )}
      {f && f.subscriptions.length > 0 && (
        <section>
          <p className="kicker">Standing charges this month</p>
          <ul className="tally">
            {f.subscriptions.map((sub) => (
              <li key={sub.merchant}>
                <span className="payee">{sub.merchant}</span>
                <span className="fig">
                  {sub.price_change_pct > 5 && <span className="rise"><ArrowUpIcon size={12} /> {pct(sub.price_change_pct, 1, true)} </span>}
                  {rupees(sub.amount)}
                </span>
              </li>
            ))}
          </ul>
          <Link to="/recurring" className="link-arrow">All recurring payments</Link>
        </section>
      )}
    </>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker={`Folio · ${monthLong(month)}`} title={`${monthName(month)} folio`} />
      <nav className="month-tabs" aria-label="Choose a month">
        {months.slice(0, 12).map((m) => (
          <button key={m} type="button" className="month-tab" aria-pressed={m === month} onClick={() => onMonth(m)}>
            {monthShort(m)} <span className="fig">{m.slice(2, 4)}</span>
          </button>
        ))}
      </nav>

      {facts.loading && <Loading what={`${monthName(month)}`} />}
      {facts.error && <ErrorNote error={facts.error} onRetry={facts.reload} />}
      {f && (
        <>
          <HeroFigure
            label="Net this month"
            value={rupees(f.net_savings)}
            note={f.savings_rate_pct != null
              ? f.net_savings >= 0 ? `You kept ${f.savings_rate_pct}% of what came in.` : "More went out than came in."
              : "No income recorded this month yet."}
          />

          <div className="jama-naam">
            <div className="jama-naam__col">
              <p className="kicker">Jama · money in</p>
              <p className="jama-naam__figure"><Rupees value={f.income} /></p>
              <p className="small muted">salary, refunds, interest; transfers from your own accounts aren't counted</p>
            </div>
            <div className="jama-naam__col">
              <p className="kicker">Naam · money out</p>
              <p className="jama-naam__figure"><Rupees value={f.expenses} /></p>
              <p className="small muted">spending only; investments and transfers to your own accounts are left out</p>
            </div>
          </div>

          {f.unreviewed_transactions > 0 && (
            <p className="note"><Highlight>{f.unreviewed_transactions} entries this month are still unposted</Highlight> — these totals will move once they're reviewed.</p>
          )}

          <Section title="Where it went" kicker={`${monthName(month)} spending by category`}>
            {f.top_categories.length ? <RuledBars data={f.top_categories.map((c) => ({ label: c.category, value: c.amount, share: c.share_pct }))}
              caption={`Spending by category, ${monthLong(month)}`} />
              : <p className="muted">No spending recorded.</p>}
          </Section>

          {f.big_changes_vs_last_month.length > 0 && (
            <Section title="Moved since last month" kicker="Changes over 20% and ₹500">
              <table className="ruled">
                <thead><tr><th scope="col">Category</th><th scope="col" className="num">Last month</th><th scope="col" className="num">This month</th><th scope="col" className="num">Change</th></tr></thead>
                <tbody className="stagger">
                  {f.big_changes_vs_last_month.map((c) => (
                    <tr key={c.category}>
                      <th scope="row">{c.category}</th>
                      <td className="num fig">{rupees(c.last_month)}</td>
                      <td className="num fig">{rupees(c.this_month)}</td>
                      <td className={`num fig ${c.change_pct > 0 ? "rise" : "fall"}`}>
                        {c.change_pct > 0 ? <ArrowUpIcon size={12} /> : <ArrowDownIcon size={12} />} {pct(c.change_pct, 0, true)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          )}

          <Section title="Paid the most" kicker="Top payees">
            <table className="ruled">
              <thead><tr><th scope="col">Payee</th><th scope="col" className="num">Entries</th><th scope="col" className="num">Total</th></tr></thead>
              <tbody className="stagger">
                {f.top_merchants.map((m) => (
                  <tr key={m.merchant}>
                    <th scope="row">{m.merchant}</th>
                    <td className="num fig">{m.count}</td>
                    <td className="num fig">{rupees(m.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </>
      )}
    </Sheet>
  );
}
