// "Entries awaiting your initials" (review) and "Spot-check the confident ones" (audit).
// One card at a time. Keys: Enter = accept the model's suggestion, 1-9 = quick category, / = search, S = skip.
// Accepting presses a stamp (the signature motion), then the queue is re-read, because one answer can
// compile a rule that fixes other entries, or flag siblings of a corrected model answer.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FolioHead, Sheet } from "../components/Book";
import { ErrorNote, Loading } from "../components/Controls";
import { EntryCard } from "../components/EntryCard";
import { Stamp } from "../components/Ledger";
import { useSlip } from "../components/Toast";
import { api } from "../lib/api";
import { quickPicks } from "../lib/categories";
import { splitCategory } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { CorrectionResult, ReviewItem } from "../lib/types";

const STAMP_MS = 420;

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface Posted { id: number; merchant: string; category: string; ruleCreated: boolean; propagated: number }

export function ReviewPage({ mode }: { mode: "review" | "audit" }) {
  const categories = useAsync(api.categories, []);
  const [queue, setQueue] = useState<ReviewItem[]>();
  const [error, setError] = useState<Error>();
  const [skipped, setSkipped] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [stampedId, setStampedId] = useState<number | null>(null);
  const [posted, setPosted] = useState<Posted[]>([]);
  const pickerRef = useRef<HTMLInputElement>(null);
  const slip = useSlip();

  const load = useCallback(async () => {
    try {
      setError(undefined);
      setQueue(mode === "audit" ? await api.audit(5) : await api.review(100));
    } catch (e) {
      setError(e as Error);
    }
  }, [mode]);

  useEffect(() => { setQueue(undefined); setSkipped([]); setPosted([]); void load(); }, [load]);

  const visible = useMemo(() => (queue ?? []).filter((i) => !skipped.includes(i.id)), [queue, skipped]);
  const item = visible[0];
  const picks = useMemo(() => quickPicks(item?.suggestion ?? null), [item]);

  const commit = useCallback(async (run: () => Promise<CorrectionResult>) => {
    if (!item || busy) return;
    setBusy(true);
    try {
      const r = await run();
      setStampedId(item.id);
      await new Promise((res) => setTimeout(res, prefersReducedMotion() ? 0 : STAMP_MS));
      setPosted((p) => [{ id: item.id, merchant: item.merchant, category: r.category, ruleCreated: r.rule_created != null,
        propagated: r.propagated }, ...p].slice(0, 12));
      if (r.rule_created != null) {
        slip(`Rule learned for ${item.merchant}`,
          r.propagated ? `${r.propagated} more ${r.propagated === 1 ? "entry was" : "entries were"} posted with it. The model won't be asked about this payee again.`
            : "From now on this payee is posted without asking the model.", "cleared");
      } else if (r.siblings_flagged) {
        slip(`${r.siblings_flagged} earlier ${r.siblings_flagged === 1 ? "answer" : "answers"} for ${item.merchant} sent back for review`,
          "The model was confidently wrong here, so its matching answers for this payee are in question too.", "ink");
      } else if (r.rules_invalidated) {
        slip("An old rule was retired", "Your answer contradicted a rule the book had learned, so it stopped trusting it.", "ink");
      }
      if (mode === "audit") setQueue((q) => (q ?? []).filter((i) => i.id !== item.id));
      else await load();
    } catch (e) {
      slip("Couldn't post that entry", (e as Error).message, "critical");
    } finally {
      setStampedId(null);
      setBusy(false);
    }
  }, [item, busy, load, mode, slip]);

  const accept = useCallback(() => {
    if (item?.suggestion && item.review_reason !== "suspicious_text") void commit(() => api.accept(item.id));
  }, [item, commit]);
  const choose = useCallback((c: string) => { if (item) void commit(() => api.setCategory(item.id, c)); }, [item, commit]);
  const skip = useCallback(() => { if (item) setSkipped((s) => [...s, item.id]); }, [item]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (t.closest("button, a") && e.key === "Enter") return;   // let focused buttons keep their Enter
      if (e.key === "Enter") { e.preventDefault(); accept(); }
      else if (e.key === "/") { e.preventDefault(); pickerRef.current?.focus(); }
      else if (e.key === "s" || e.key === "S") { e.preventDefault(); skip(); }
      else if (/^[1-9]$/.test(e.key)) {
        const c = picks[Number(e.key) - 1];
        if (c) { e.preventDefault(); choose(c); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [accept, choose, skip, picks]);

  const head = mode === "audit"
    ? <FolioHead kicker="Audit · confident answers" title="Spot-check the confident ones">
        The review queue only sees entries the model was unsure about. Mistakes it was <em>sure</em> about never
        reach you there, so here are a few of its most consequential confident answers, one payee each.
      </FolioHead>
    : <FolioHead kicker="Review · human in the loop" title="Entries awaiting your initials">
        The model's guesses are pencilled in. Initial them, correct them, or leave them for later. Every answer
        teaches the book: two matching corrections for a payee become a rule.
      </FolioHead>;

  const aside = (
    <>
      <section>
        <p className="kicker">Keys</p>
        <ul className="keys">
          <li><kbd>Enter</kbd> initial the pencilled suggestion</li>
          <li><kbd>1</kbd>–<kbd>9</kbd> post under a listed category</li>
          <li><kbd>/</kbd> search every category</li>
          <li><kbd>S</kbd> leave it for later</li>
        </ul>
      </section>
      <section>
        <p className="kicker">Posted this sitting</p>
        {posted.length === 0 ? <p className="small muted">Nothing yet.</p> : (
          <ul className="posted stagger">
            {posted.map((p) => {
              const { group, name } = splitCategory(p.category);
              return (
                <li key={p.id}>
                  <span className="posted__merchant">{p.merchant}</span>
                  <span className="small secondary">{group ? `${group} · ` : ""}{name}</span>
                  {p.ruleCreated && <span className="small"><Stamp kind="rule" size="sm" label={`Rule${p.propagated ? ` +${p.propagated}` : ""}`} /></span>}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );

  if (error) return <Sheet aside={aside}>{head}<ErrorNote error={error} onRetry={load} /></Sheet>;
  if (!queue || !categories.data) return <Sheet aside={aside}>{head}<Loading what="the waiting entries" /></Sheet>;

  if (!item) {
    return (
      <Sheet aside={aside}>
        {head}
        <div className="all-clear ink-in">
          <Stamp kind="posted" label={mode === "audit" ? "Nothing to check" : "All posted"} />
          <p className="secondary">
            {mode === "audit"
              ? "Every confident answer left in the book is already backed by one of your own decisions."
              : skipped.length ? `You left ${skipped.length} for later. They'll be here next time.`
                : "Nothing awaits your initials. New statements will bring new entries."}
          </p>
          <p><Link to="/ledger" className="link-arrow">Read the ledger</Link></p>
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet aside={aside}>
      {head}
      <EntryCard
        key={item.id}
        ref={pickerRef}
        item={item}
        mode={mode}
        remaining={visible.length}
        categories={categories.data}
        quickPicks={picks}
        busy={busy}
        stamped={stampedId === item.id}
        onAccept={accept}
        onChoose={choose}
        onSkip={skip}
      />
    </Sheet>
  );
}
