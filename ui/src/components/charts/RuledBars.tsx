// Spend by category: one series, horizontal bars INSIDE ruled table rows (DESIGN.md "Charts").
// Bars <= 24px (here 10px), 4px rounded data-end, square at the baseline, value at the tip, and a
// hover/focus tooltip that adds share and rank. The table itself is the accessible table view.
import { rupees } from "../../lib/format";
import { splitCategory } from "../../lib/format";

export interface BarDatum { label: string; value: number; share?: number }

export function RuledBars({ data, caption }: { data: BarDatum[]; caption: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <table className="ruled bars">
      <caption className="sr-only">{caption}</caption>
      <thead className="sr-only">
        <tr><th scope="col">Category</th><th scope="col">Amount</th></tr>
      </thead>
      <tbody className="stagger">
        {data.map((d, i) => {
          const { group, name } = splitCategory(d.label);
          const w = (d.value / max) * 100;
          return (
            <tr key={d.label} className="bar-row" tabIndex={0}>
              <th scope="row" className="bar-row__label">
                <span className="cat__group">{group ? `${group} · ` : ""}</span>{name}
              </th>
              <td className="bar-row__cell">
                <span className="bar-row__track">
                  <span className="bar-row__bar" style={{ width: `max(${w}%, 2px)` }} />
                  <span className="bar-row__value fig">{rupees(d.value)}</span>
                </span>
                <span className="chart-tip" role="tooltip">
                  <strong className="fig">{rupees(d.value)}</strong>
                  <span>{d.share != null ? `${d.share}% of spending · ` : ""}#{i + 1} this month</span>
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
