// An import result, printed like a counter receipt with a torn edge.
import type { ImportResult } from "../lib/types";
import { Stamp } from "./Ledger";

export function Receipt({ file, result, error }: { file: string; result?: ImportResult; error?: string }) {
  return (
    <article className="receipt" aria-label={`Receipt for ${file}`}>
      <p className="receipt__head fig">{file}</p>
      {error ? (
        <>
          <p className="receipt__line"><span>Status</span><span className="receipt__bad">Refused</span></p>
          <p className="receipt__error">{error}</p>
          <p className="receipt__stamp"><Stamp kind="mismatch" label="Not posted" /></p>
        </>
      ) : result ? (
        <>
          <p className="receipt__line"><span>Account</span><span>{result.account}</span></p>
          <p className="receipt__line"><span>Format</span><span>{result.profile_name === "heuristic" ? "recognised" : result.profile_name}</span></p>
          <p className="receipt__rule" aria-hidden="true" />
          <p className="receipt__line"><span>Rows read</span><span>{result.rows_total}</span></p>
          <p className="receipt__line"><span>New entries</span><strong>{result.rows_new}</strong></p>
          <p className="receipt__line"><span>Already in the book</span><span>{result.rows_duplicate}</span></p>
          <p className="receipt__line"><span>Rejected rows</span><span>{result.rows_rejected}</span></p>
          {result.rejects.slice(0, 3).map(([row, why]) => (
            <p key={row} className="receipt__reject">row {row}: {why}</p>
          ))}
          <p className="receipt__stamp">
            {result.balance_check === "ok" ? <Stamp kind="reconciled" />
              : result.balance_check === "mismatch" ? <Stamp kind="mismatch" label={`${result.balance_mismatches} balance mismatches`} />
              : <Stamp kind="unchecked" />}
          </p>
        </>
      ) : (
        <p className="receipt__line"><span>Reading the statement…</span><span /></p>
      )}
    </article>
  );
}
