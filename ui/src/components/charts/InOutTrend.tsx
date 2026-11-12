// Money in vs money out by month. Two 2px lines (validated palette: --series-out / --series-in),
// end dots r=4 with a 2px paper ring, legend + direct end labels (text in ink, never series color),
// ONE y-axis, crosshair tooltip listing both series (pointer and arrow keys), and a table view.
import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { compactRupees, money, monthLong, monthShort } from "../../lib/format";
import type { TrendPoint } from "../../lib/types";

const W = 280;
const H = 196;
const PAD = { top: 14, right: 70, bottom: 28, left: 40 };   // right pad fits the direct end labels

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(v / 3));
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * step * 3);
  return candidates.find((c) => c >= v) ?? v;
}

export function InOutTrend({ data }: { data: TrendPoint[] }) {
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  const pts = useMemo(() => data.map((d) => ({ ...d, in: d.money_in / 100, out: d.money_out / 100 })), [data]);
  const top = niceMax(Math.max(0, ...pts.flatMap((p) => [p.in, p.out])));
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (pts.length <= 1 ? iw / 2 : (i / (pts.length - 1)) * iw);
  const y = (v: number) => PAD.top + ih - (v / top) * ih;
  const path = (key: "in" | "out") => pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
  const ticks = [0, top / 3, (2 * top) / 3, top];
  const last = pts.length - 1;

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    pts.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
    setActive(best);
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowRight") setActive((a) => Math.min((a ?? -1) + 1, last));
    else if (e.key === "ArrowLeft") setActive((a) => Math.max((a ?? last + 1) - 1, 0));
    else if (e.key === "Escape") setActive(null);
  };

  if (!pts.length) return <p className="muted small">No months posted yet.</p>;
  const a = active != null ? pts[active] : undefined;

  return (
    <figure className="chart">
      <figcaption className="chart__head">
        <span className="h-section" id={`${id}-t`}>In and out, by month</span>
        <ul className="legend" aria-label="Legend">
          <li><span className="legend__key legend__key--in" aria-hidden="true" />Money in</li>
          <li><span className="legend__key legend__key--out" aria-hidden="true" />Money out</li>
        </ul>
      </figcaption>

      {asTable ? (
        <table className="ruled chart__table">
          <thead><tr><th scope="col">Month</th><th scope="col">In</th><th scope="col">Out</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.month}>
                <th scope="row">{monthLong(d.month)}</th>
                <td className="fig">{money(d.money_in, "never", false)}</td>
                <td className="fig">{money(d.money_out, "never", false)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="chart__plot">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${id}-t`} aria-describedby={`${id}-d`} tabIndex={0}
            onPointerMove={onMove} onPointerLeave={() => setActive(null)} onKeyDown={onKey} onBlur={() => setActive(null)}>
            <desc id={`${id}-d`}>Use the left and right arrow keys to read each month.</desc>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "chart__base" : "chart__grid"} />
                <text x={PAD.left - 6} y={y(t)} className="chart__tick" textAnchor="end" dominantBaseline="middle">{compactRupees(t)}</text>
              </g>
            ))}
            {pts.map((p, i) => (
              <text key={p.month} x={x(i)} y={H - 8} className="chart__tick" textAnchor="middle">{monthShort(p.month)}</text>
            ))}
            {a && active != null && <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={PAD.top + ih} className="chart__cross" />}
            <path d={path("out")} className="chart__line chart__line--out" />
            <path d={path("in")} className="chart__line chart__line--in" />
            {(["out", "in"] as const).map((k) => {
              const i = active ?? last;
              const p = pts[i];
              if (!p) return null;
              return <circle key={k} cx={x(i)} cy={y(p[k])} r={4} className={`chart__dot chart__dot--${k}`} />;
            })}
            {active == null && pts[last] && (() => {
              const p = pts[last]!;
              let yi = y(p.in);
              let yo = y(p.out);
              if (Math.abs(yi - yo) < 13) { const mid = (yi + yo) / 2; yi = mid + (p.in >= p.out ? -7 : 7); yo = mid + (p.out > p.in ? -7 : 7); }
              return (
                <>
                  <text x={x(last) + 8} y={yi} className="chart__end" dominantBaseline="middle">In {compactRupees(p.in)}</text>
                  <text x={x(last) + 8} y={yo} className="chart__end" dominantBaseline="middle">Out {compactRupees(p.out)}</text>
                </>
              );
            })()}
          </svg>
          {a && active != null && (
            <div className="chart-tip chart-tip--float" role="tooltip"
              style={{ left: `${(x(active) / W) * 100}%` }}>
              <span className="chart-tip__title">{monthLong(a.month)}</span>
              <span className="chart-tip__row"><span className="legend__key legend__key--in" aria-hidden="true" /><strong className="fig">{money(a.money_in, "never", false)}</strong> in</span>
              <span className="chart-tip__row"><span className="legend__key legend__key--out" aria-hidden="true" /><strong className="fig">{money(a.money_out, "never", false)}</strong> out</span>
            </div>
          )}
        </div>
      )}
      <button type="button" className="link-btn" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
        {asTable ? "Show as chart" : "Show as table"}
      </button>
    </figure>
  );
}
