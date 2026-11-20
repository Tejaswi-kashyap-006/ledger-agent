// "Post a statement": a letterbox for CSV and PDF statements; every file comes back as a receipt.
import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { FolioHead, Section, Sheet } from "../components/Book";
import { Button, TextField } from "../components/Controls";
import { UploadIcon } from "../components/Icons";
import { Receipt } from "../components/Receipt";
import { useSlip } from "../components/Toast";
import { api } from "../lib/api";
import { useAsync } from "../lib/hooks";
import type { ImportResult, ProcessResult } from "../lib/types";

interface Posting { file: string; result?: ImportResult; error?: string }

const isPdf = (f: File) => /\.pdf$/i.test(f.name) || f.type === "application/pdf";

export function PostStatementPage() {
  const accounts = useAsync(api.accounts, []);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [postings, setPostings] = useState<Posting[]>([]);
  const [posting, setPosting] = useState(false);
  const [run, setRun] = useState<ProcessResult>();
  const [processing, setProcessing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const slip = useSlip();

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const ok = Array.from(list).filter((f) => /\.(csv|txt|pdf)$/i.test(f.name));
    if (ok.length < list.length) slip("Only CSV and PDF statements can be posted", "Download the statement as CSV or PDF from your bank's net-banking. Shop bills go on the Bills page.", "critical");
    setFiles((prev) => [...prev, ...ok.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    addFiles(e.dataTransfer.files);
  };

  const postAll = async () => {
    if (!account.trim() || !files.length) return;
    setPosting(true);
    setRun(undefined);
    const queue = [...files];
    setFiles([]);
    for (const f of queue) {
      setPostings((p) => [{ file: f.name }, ...p]);
      try {
        const result = await api.importFile(account.trim(), f, isPdf(f) ? password : undefined);
        setPostings((p) => p.map((x) => (x.file === f.name && !x.result && !x.error ? { ...x, result } : x)));
      } catch (e) {
        setPostings((p) => p.map((x) => (x.file === f.name && !x.result && !x.error ? { ...x, error: (e as Error).message } : x)));
      }
    }
    setPosting(false);
    setPassword("");          // used once, then forgotten
    accounts.reload();
  };

  const processNow = async () => {
    setProcessing(true);
    try {
      const r = await api.process();
      setRun(r);
      if (r.status === "paused_budget") slip("Paused at the token budget", "Run it again to continue where it stopped.", "ink");
    } catch (e) {
      slip("Processing stopped", (e as Error).message, "critical");
    } finally {
      setProcessing(false);
    }
  };

  const newEntries = postings.reduce((n, p) => n + (p.result?.rows_new ?? 0), 0);
  const hasPdf = files.some(isPdf);

  const aside = (
    <>
      <section>
        <p className="kicker">What the book accepts</p>
        <ul className="notes">
          <li>CSV exports and PDF e-statements from any Indian bank or card: HDFC, ICICI, SBI, Axis and the rest.</li>
          <li>Locked PDFs open with the password your bank set. It is used once and never stored.</li>
          <li>A new layout is learned once and remembered, so the next statement from that bank costs nothing.</li>
          <li>Where the export has a running balance, every row is checked against it to the paisa.</li>
          <li>Overlapping statements are safe. Entries already in the book are skipped, never doubled.</li>
        </ul>
      </section>
      <section>
        <p className="kicker">No statements handy?</p>
        <p className="small secondary">Run <code className="fig">ledger demo</code> in a terminal. It writes three months of realistic
          HDFC and ICICI card statements to <code className="fig">sample_data/</code>, plus a September HDFC
          statement as a PDF.</p>
      </section>
    </>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Import" title="Post a statement">
        Drop in the CSV or PDF statement your bank lets you download. The book reads it, learns its layout, and
        writes every entry in once.
      </FolioHead>

      <div className="post-form">
        <TextField label="Account" list="known-accounts" value={account} onChange={(e) => setAccount(e.target.value)}
          placeholder="e.g. HDFC Savings" hint="Statements from the same account must share a name. That's how duplicates are recognised."
          required />
        <datalist id="known-accounts">
          {accounts.data?.map((a) => <option key={a.id} value={a.name} />)}
        </datalist>

        <label
          className={`letterbox${over ? " is-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <input ref={input} type="file" accept=".csv,.txt,text/csv,.pdf,application/pdf" multiple className="sr-only"
            onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          <span className="letterbox__slot" aria-hidden="true" />
          <UploadIcon size={20} />
          <span className="letterbox__title">Drop statements here, or choose files</span>
          <span className="small muted">CSV or PDF · up to 10 MB each · several at once is fine</span>
        </label>

        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f) => (
              <li key={`${f.name}-${f.size}`}>
                <span className="fig">{f.name}</span>
                <span className="small muted">{(f.size / 1024).toFixed(1)} KB</span>
                <button type="button" className="link-btn" onClick={() => setFiles((l) => l.filter((x) => x !== f))}>remove</button>
              </li>
            ))}
          </ul>
        )}

        {hasPdf && (
          <TextField label="PDF password (if it's locked)" type="password" autoComplete="off" value={password}
            onChange={(e) => setPassword(e.target.value)} placeholder="leave empty if the PDF opens without one"
            hint="Banks often lock e-statements with your name, date of birth or customer ID. Used once to open the file, never stored." />
        )}

        <Button onClick={postAll} disabled={posting || !account.trim() || !files.length}>
          {posting ? "Posting…" : files.length > 1 ? `Post ${files.length} statements` : "Post statement"}
        </Button>
        {!account.trim() && files.length > 0 && <p className="field__hint">Name the account first.</p>}
      </div>

      {postings.length > 0 && (
        <Section title="Receipts" kicker="This sitting">
          <div className="receipts">
            {postings.map((p, i) => <Receipt key={`${p.file}-${i}`} file={p.file} result={p.result} error={p.error} />)}
          </div>
          {newEntries > 0 && !run && (
            <div className="next-step">
              <p>{newEntries} new {newEntries === 1 ? "entry is" : "entries are"} in the book, not yet categorised.</p>
              <Button onClick={processNow} disabled={processing}>{processing ? "Categorising…" : "Categorise them now"}</Button>
            </div>
          )}
          {run && (
            <div className="next-step">
              <p>
                <strong>{run.stats.processed - run.stats.to_review}</strong> of {run.stats.processed} posted automatically
                ({run.stats.by_rule} by rules{run.stats.transfer_matches ? `, ${run.stats.transfer_matches} of them transfers between your accounts` : ""}, {run.stats.by_llm} by the model).
                {run.stats.to_review > 0 && <> <strong>{run.stats.to_review}</strong> need your initials.</>}
              </p>
              {run.stats.to_review > 0 && <Link to="/review" className="btn btn--ink">Review them</Link>}
            </div>
          )}
        </Section>
      )}
    </Sheet>
  );
}
