// "Standing charges": subscriptions, EMIs, rent - found statistically, no model involved.
import { FolioHead, Sheet } from "../components/Book";
import { ErrorNote, Loading } from "../components/Controls";
import { ArrowDownIcon, ArrowUpIcon } from "../components/Icons";
import { HeroFigure } from "../components/Ledger";
import { api } from "../lib/api";
import { day, money, pct, splitCategory } from "../lib/format";
import { useAsync } from "../lib/hooks";

const CADENCE: Record<string, string> = { weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", yearly: "Yearly" };

export function StandingChargesPage() {
  const subs = useAsync(api.subscriptions, []);
  const monthly = subs.data?.reduce((s, r) => s + r.monthly_cost_minor, 0) ?? 0;
  const rises = subs.data?.filter((r) => r.price_change_pct > 5) ?? [];

  const aside = (
    <section>
      <p className="kicker">How these are found</p>
      <p className="small secondary">A payee counts as a standing charge when it has charged you at least three times, at a regular
        interval (weekly, monthly, quarterly or yearly), for a similar amount. This is plain statistics — no model is involved,
        so nothing here is a guess.</p>
      <p className="small secondary">A <span className="rise">price rise</span> means the latest charge is noticeably higher than
        what this payee usually charges.</p>
    </section>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Recurring · subscriptions, EMIs, rent" title="Standing charges" />
      {subs.loading && <Loading what="the standing charges" />}
      {subs.error && <ErrorNote error={subs.error} onRetry={subs.reload} />}
      {subs.data && subs.data.length === 0 && (
        <p className="secondary">No standing charges found yet. They show up once a payee has charged you three times on a regular schedule.</p>
      )}
      {subs.data && subs.data.length > 0 && (
        <>
          <HeroFigure label="Committed every month" value={money(monthly, "never", false)}
            note={rises.length ? `${rises.length} ${rises.length === 1 ? "charge has" : "charges have"} gone up in price.` : "No price rises spotted."} />
          <div className="table-scroll">
            <table className="ruled charges">
              <thead>
                <tr>
                  <th scope="col">Payee</th><th scope="col">Cadence</th>
                  <th scope="col" className="num">Last charge</th><th scope="col" className="num">Per month</th>
                  <th scope="col" className="num">Change</th><th scope="col">Next due</th>
                </tr>
              </thead>
              <tbody className="stagger">
                {subs.data.map((r) => {
                  const { group, name } = splitCategory(r.category);
                  return (
                    <tr key={r.merchant}>
                      <th scope="row">
                        <span className="ledger__payee">{r.merchant}</span>
                        <span className="small muted">{group ? `${group} · ` : ""}{name} · {r.occurrences} charges</span>
                      </th>
                      <td>{CADENCE[r.cadence] ?? r.cadence}</td>
                      <td className="num fig">{money(r.last_amount_minor, "never")}</td>
                      <td className="num fig">{money(r.monthly_cost_minor, "never", false)}</td>
                      <td className={`num fig ${r.price_change_pct > 5 ? "rise" : r.price_change_pct < -5 ? "fall" : "muted"}`}>
                        {r.price_change_pct > 5 && <><ArrowUpIcon size={12} /> </>}
                        {r.price_change_pct < -5 && <><ArrowDownIcon size={12} /> </>}
                        {Math.abs(r.price_change_pct) < 1 ? <span aria-label="steady">steady</span> : pct(r.price_change_pct, 1, true)}
                        {r.price_change_pct > 5 && <span className="sr-only"> price rise</span>}
                      </td>
                      <td className="fig nowrap">{day(r.next_expected, true)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Sheet>
  );
}
