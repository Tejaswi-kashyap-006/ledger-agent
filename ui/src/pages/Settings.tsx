// "Rules, memory & keys": everything the book has learned or been told, editable by you.
import { useEffect, useState } from "react";
import { FolioHead, Section, Sheet } from "../components/Book";
import { CategoryPicker } from "../components/CategoryPicker";
import { Button, ErrorNote, Loading, SelectField, TextArea, TextField } from "../components/Controls";
import { Stamp } from "../components/Ledger";
import { useSlip } from "../components/Toast";
import { api, getToken, setToken } from "../lib/api";
import { day, splitCategory } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { MemoryBlock, NewRule } from "../lib/types";

const RULE_KIND: Record<string, string> = { merchant: "payee is", contains: "narration contains", regex: "narration matches" };

const BLOCK_TITLES: Record<string, string> = {
  household: "Household",
  preferences: "Preferences",
  goals: "Goals",
};

function MemorySlip({ block, onSaved }: { block: MemoryBlock; onSaved: () => void }) {
  const [value, setValue] = useState(block.value);
  const [saving, setSaving] = useState(false);
  const slip = useSlip();
  useEffect(() => setValue(block.value), [block.value]);
  const over = value.length > block.char_limit;
  const save = async () => {
    setSaving(true);
    try {
      await api.putMemoryBlock(block.label, value);
      slip(`${BLOCK_TITLES[block.label] ?? block.label} saved`, "Used from the next categorisation and every question.", "cleared");
      onSaved();
    } catch (e) {
      slip("Couldn't save", (e as Error).message, "critical");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="memory-slip">
      <TextArea label={BLOCK_TITLES[block.label] ?? block.label} hint={block.description} value={value} rows={4}
        onChange={(e) => setValue(e.target.value)} />
      <div className="memory-slip__foot">
        <span className={`fig small ${over ? "rise" : "muted"}`}>{value.length}/{block.char_limit}</span>
        <Button variant="quiet" onClick={save} disabled={saving || over || value === block.value}>{saving ? "Saving…" : "Save"}</Button>
      </div>
    </div>
  );
}

export function SettingsPage() {
  const blocks = useAsync(api.memoryBlocks, []);
  const facts = useAsync(api.memoryFacts, []);
  const rules = useAsync(api.rules, []);
  const categories = useAsync(api.categories, []);
  const stats = useAsync(api.stats, []);
  const health = useAsync(api.health, []);
  const slip = useSlip();
  const [token, setTokenState] = useState(getToken());
  const [rule, setRule] = useState<NewRule>({ pattern_type: "merchant", pattern: "", category: "", direction: null });

  const addRule = async () => {
    try {
      await api.addRule(rule);
      slip("Rule added", `${rule.pattern} → ${rule.category}. It applies to entries processed from now on.`, "cleared");
      setRule({ pattern_type: "merchant", pattern: "", category: "", direction: null });
      rules.reload();
    } catch (e) {
      slip("Couldn't add the rule", (e as Error).message, "critical");
    }
  };

  const aside = (
    <>
      <section>
        <p className="kicker">This server</p>
        <ul className="tally">
          <li><span>language model</span><span>{health.data ? (health.data.llm ? "configured" : "not configured") : "…"}</span></li>
          <li><span>entries</span><span className="fig">{stats.data?.transactions ?? "…"}</span></li>
          <li><span>your decisions</span><span className="fig">{stats.data?.verified_labels ?? "…"}</span></li>
        </ul>
      </section>
      <section>
        <p className="kicker">Access key</p>
        <TextField label="Bearer token" type="password" value={token} onChange={(e) => setTokenState(e.target.value)}
          hint="Only needed if the server sets LEDGER_API_KEY. Stored in this browser only." autoComplete="off" />
        <Button variant="quiet" onClick={() => { setToken(token.trim()); slip("Key saved in this browser"); }}>Save key</Button>
      </section>
    </>
  );

  return (
    <Sheet aside={aside}>
      <FolioHead kicker="Settings · what the book knows" title="Rules, memory & keys">
        Everything the book has learned or been told lives here, and all of it is yours to correct.
      </FolioHead>

      <Section title="Memory" kicker="Pinned into every categorisation and every question">
        {blocks.error && <ErrorNote error={blocks.error} onRetry={blocks.reload} />}
        {blocks.loading && <Loading what="memory" />}
        <div className="memory-grid">
          {blocks.data?.map((b) => <MemorySlip key={b.label} block={b} onSaved={blocks.reload} />)}
        </div>
      </Section>

      <Section title="Remembered facts" kicker="Told to the munim, recalled when relevant">
        {facts.data?.length === 0 && <p className="muted small">Nothing yet. Tell the munim something worth remembering.</p>}
        <ul className="facts">
          {facts.data?.map((f) => (
            <li key={f.id}>
              <span>{f.text}</span>
              <span className="small muted fig">{day(f.created_at.slice(0, 10), true)}</span>
              <Button variant="quiet" onClick={async () => { await api.forgetFact(f.id); facts.reload(); }}>Forget</Button>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Rules" kicker="Run before the model: free, instant, exact">
        {rules.error && <ErrorNote error={rules.error} onRetry={rules.reload} />}
        <div className="table-scroll">
          <table className="ruled rules-table">
            <thead>
              <tr><th scope="col">When</th><th scope="col">Post under</th><th scope="col">Source</th><th scope="col" className="num">Used</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {rules.data?.map((r) => {
                const { group, name } = splitCategory(r.category);
                return (
                  <tr key={r.id}>
                    <td><span className="small muted">{RULE_KIND[r.pattern_type]}</span> <strong>{r.pattern}</strong>{r.direction ? <span className="small muted"> · {r.direction}s only</span> : null}</td>
                    <td>{group ? <span className="muted">{group} · </span> : null}{name}</td>
                    <td>{r.source === "compiled" ? <Stamp kind="rule" size="sm" label="Learned" /> : <Stamp kind="verified" size="sm" label="Yours" />}</td>
                    <td className="num fig">{r.hits}</td>
                    <td className="num"><Button variant="quiet" onClick={async () => { await api.deleteRule(r.id); rules.reload(); }}>Retire</Button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {rules.data?.length === 0 && <p className="muted small">No rules yet. They appear when you add one, or after two matching corrections.</p>}

        <div className="rule-form">
          <SelectField label="Match" value={rule.pattern_type} onChange={(e) => setRule({ ...rule, pattern_type: e.target.value as NewRule["pattern_type"] })}>
            <option value="merchant">payee is exactly</option>
            <option value="contains">narration contains</option>
            <option value="regex">narration matches regex</option>
          </SelectField>
          <TextField label="Pattern" value={rule.pattern} onChange={(e) => setRule({ ...rule, pattern: e.target.value })} placeholder="e.g. ZOMATO" />
          <SelectField label="Direction" value={rule.direction ?? ""} onChange={(e) => setRule({ ...rule, direction: (e.target.value || null) as NewRule["direction"] })}>
            <option value="">money in or out</option>
            <option value="debit">money out only</option>
            <option value="credit">money in only</option>
          </SelectField>
          <div>
            {categories.data && <CategoryPicker categories={categories.data} label={rule.category ? `Post under · ${rule.category}` : "Post under"}
              onSelect={(c) => setRule({ ...rule, category: c })} />}
          </div>
          <Button onClick={addRule} disabled={!rule.pattern.trim() || !rule.category}>Add rule</Button>
        </div>
      </Section>

      {stats.data && stats.data.llm.length > 0 && (
        <Section title="Model usage" kicker="From the audit log of every call">
          <div className="table-scroll">
            <table className="ruled">
              <thead><tr><th scope="col">Purpose</th><th scope="col" className="num">Calls</th><th scope="col" className="num">Tokens in</th>
                <th scope="col" className="num">Tokens out</th><th scope="col" className="num">Cache hits</th><th scope="col" className="num">Errors</th></tr></thead>
              <tbody>
                {stats.data.llm.map((l) => (
                  <tr key={l.purpose}>
                    <th scope="row">{l.purpose.replace("_", " ")}</th>
                    <td className="num fig">{l.calls}</td><td className="num fig">{(l.i ?? 0).toLocaleString("en-IN")}</td>
                    <td className="num fig">{(l.o ?? 0).toLocaleString("en-IN")}</td><td className="num fig">{l.hits ?? 0}</td>
                    <td className="num fig">{l.errors ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Sheet>
  );
}
