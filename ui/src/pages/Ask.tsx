// "Ask the munim": questions about your own money, answered by the tool-using agent.
// Each answer carries footnote-style marginalia listing the tools it consulted (the agent shows its work).
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { FolioHead, Sheet } from "../components/Book";
import { Button } from "../components/Controls";
import { Pencil } from "../components/Ledger";
import { ApiError, api } from "../lib/api";
import { useStoredState } from "../lib/hooks";
import { RichText } from "../lib/richText";
import type { ToolCallLog } from "../lib/types";

interface Exchange { q: string; a?: string; tools?: ToolCallLog[]; error?: string; stop?: string }

const SUGGESTIONS = [
  "How much did we spend on food delivery last month?",
  "What are my subscriptions, and did any get more expensive?",
  "Which month did we spend the most on groceries?",
  "How much rent have I paid this year?",
  "My landlord is Ramesh Kumar — remember that.",
];

export function describeTool(t: ToolCallLog): string {
  const a = t.args as Record<string, unknown>;
  switch (t.name) {
    case "spending_summary":
      return `spending summary · ${a.start_date} → ${a.end_date} by ${a.group_by} (${a.direction})`;
    case "search_transactions":
      return `searched entries${a.text ? ` for “${a.text}”` : ""}${a.category ? ` in ${a.category}` : ""}`;
    case "run_sql":
      return "read the ledger with a query";
    case "recurring_payments":
      return "checked recurring payments";
    case "memory_update":
      return `noted in memory (${a.block})`;
    case "remember":
      return "remembered a fact";
    case "propose_recategorization":
      return `proposed a change for review (${a.category})`;
    default:
      return t.name;
  }
}

export function AskPage() {
  const [conversation, setConversation] = useStoredState<string>("ledger.conversation", "");
  const [log, setLog] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!conversation) return;
    let live = true;
    api.conversation(conversation).then((turns) => {
      if (live) setLog(turns.map((t) => ({ q: t.question, a: t.answer })));
    }, () => {});
    return () => { live = false; };
  }, [conversation]);

  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [log.length, asking]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || asking) return;
    setDraft("");
    setAsking(true);
    setLog((l) => [...l, { q }]);
    try {
      const r = await api.chat(q, conversation || undefined);
      if (!conversation) setConversation(r.conversation_id);
      setLog((l) => l.map((x, i) => (i === l.length - 1 ? { ...x, a: r.answer, tools: r.tool_calls, stop: r.stop } : x)));
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 503
        ? "The munim needs a language model. Set OPENAI_API_KEY where `ledger serve` runs, then ask again."
        : (e as Error).message;
      setLog((l) => l.map((x, i) => (i === l.length - 1 ? { ...x, error: msg } : x)));
    } finally {
      setAsking(false);
      box.current?.focus();
    }
  };

  const onSubmit = (e: FormEvent) => { e.preventDefault(); void ask(draft); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(draft); }
  };
  const fresh = () => { setConversation(""); setLog([]); box.current?.focus(); };

  const aside = (
    <>
      <section>
        <p className="kicker">Things to ask</p>
        <ul className="suggestions">
          {SUGGESTIONS.map((s) => (
            <li key={s}><button type="button" className="suggestion" onClick={() => void ask(s)} disabled={asking}><Pencil>{s}</Pencil></button></li>
          ))}
        </ul>
      </section>
      <section>
        <p className="kicker">How the munim works</p>
        <p className="small secondary">Every figure comes from a query against your ledger — never from memory or a guess. It can read,
          and note things you tell it, but it can't change an entry: suggested corrections go to Review for your initials.</p>
        {log.length > 0 && <Button variant="quiet" onClick={fresh}>Start a fresh conversation</Button>}
      </section>
    </>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Ask · the agent" title="Ask the munim">
        The munim was the trader's trusted bookkeeper. Ask about your own money in plain words, in English or Hinglish.
      </FolioHead>

      <div className="letters" aria-live="polite">
        {log.length === 0 && <p className="muted">No questions yet. Try one from the margin.</p>}
        {log.map((x, i) => (
          <article key={i} className="letter">
            <p className="letter__q"><span className="kicker">You asked</span><span className="letter__text">{x.q}</span></p>
            {x.a && (
              <div className="letter__a">
                <p className="kicker">The munim replied</p>
                <div className="prose"><RichText text={x.a} /></div>
                {x.tools && x.tools.length > 0 && (
                  <ol className="footnotes" aria-label="Consulted">
                    {x.tools.map((t, j) => (
                      <li key={j} className={t.error ? "is-error" : ""}>consulted: {describeTool(t)}{t.error ? " — failed, retried" : ""}</li>
                    ))}
                  </ol>
                )}
                {x.stop && x.stop !== "done" && <p className="small muted">Stopped early ({x.stop.replace("_", " ")}).</p>}
              </div>
            )}
            {x.error && <p className="note note--error" role="alert">{x.error}</p>}
            {!x.a && !x.error && <p className="note note--loading">The munim is turning the pages…</p>}
          </article>
        ))}
        <div ref={bottom} />
      </div>

      <form className="ask-form" onSubmit={onSubmit}>
        <label className="kicker" htmlFor="ask-box">Your question</label>
        <textarea id="ask-box" ref={box} className="field__input field__area ask-form__box" rows={2} value={draft}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey}
          placeholder="How much went to Swiggy and Zomato in July?" />
        <div className="ask-form__row">
          <p className="small muted">Enter to ask · Shift+Enter for a new line</p>
          <Button type="submit" disabled={asking || !draft.trim()}>{asking ? "Asking…" : "Ask"}</Button>
        </div>
      </form>
    </Sheet>
  );
}
