# Code walkthrough

A guided reading order. Instead of going file by file, we follow **one transaction** from a CSV
into a report, then **one question** through the agent. Open each file as it comes up. Line references
are to functions, so they survive edits.

---

## Part 1: follow a transaction

The row, as HDFC exports it:

```
03/07/26,UPI/DR/970044521458/RAMESH KUMAR/SBIN/ramesh.kumar@oksbi/rent,000000000000,03/07/26,32000.00,,305916.00
```

### 1. `ingest/csv_reader.py`: finding the table

`read_table(data)`:
- `decode` tries `utf-8-sig`, then `utf-16`, then `cp1252`/`latin-1`. Bank exports come in all of these; the BOM-aware
  UTF-8 is first because Excel-saved CSVs often start with a BOM.
- `_sniff_delimiter` uses `csv.Sniffer` on the first 40 lines. European-style exports use `;`.
- The header row is the row among the first 40 with the most cells matching `HEADER_HINTS` (date,
  narration, withdrawal...). A preamble (account holder, period) scores 0-1, the header 5+. If nothing scores ≥ 2
  (unfamiliar column names), `_fallback_header` looks for "a row of ≥3 text cells followed by a row of
  the same width containing digits".
- Rows with fewer than 2 non-empty cells are dropped: that removes footers like `*** End of Statement ***`.
- `RawTable.signature` hashes the *normalized header*. Same layout gives the same signature, whatever the data.
  That's the key for procedural memory.

### 2. `ingest/profiles.py`: learning the layout

`resolve_profile(conn, llm, table)` is a cascade:
1. `SELECT … FROM import_profiles WHERE signature = ?`. If found, `check_profile` it anyway (banks change formats!) and reuse.
2. `heuristic_profile` maps header names with regex (`withdrawal|^debit` → `debit_column`...) and
   `detect_date_format` picks the first strptime format that parses **every** sample. Order encodes day-first
   preference, and a date like `13/02` rules out month-first automatically.
3. `llm_profile` sends the header plus 8 **redacted** sample rows and asks for an `ImportProfile` (the same
   Pydantic model is the output schema). On failure, `check.errors` goes back as `<previous_attempt_errors>`.

`check_profile` is the evaluator: `parse_rows` must succeed on ≥ 95% of rows, and `balance_consistency`
must hold. Look at how `balance_consistency` tries both orders:

```python
asc  = mismatches where  b.balance != a.balance + b.amount     # oldest first
desc = mismatches where  a.balance != b.balance + a.amount     # newest first
```

The test `test_balance_reconciliation_catches_wrong_sign` swaps the debit and credit columns and shows the import
being rejected. Without this sensor, that bug would silently flip every income and expense.

### 3. `ingest/normalize.py` and `ingest/merchant.py`: making it canonical

- `parse_amount_minor("32000.00") → 3200000`. `Decimal` all the way, with `(…)`, `Dr/Cr`, `₹`, `Rs.` and Indian
  commas handled. It returns `None` for empty cells, so split debit/credit columns work.
- `extract_merchant` runs `detect_channel` (ordered regexes: bill-pay before UPI, ATM, card...), then
  per-channel parsing. For our row: split on `/`, drop noise tokens (`UPI`, `DR`, bank codes, IFSCs,
  refs, VPAs), take the first alphabetic segment → `RAMESH KUMAR`, channel `upi`.
- `canonical_merchant` strips legal suffixes and **city names**, so `SWIGGY BANGALORE` on the card and `SWIGGY`
  on UPI share one memory key. A merchant key that isn't stable fragments every memory built on it.

### 4. `ingest/importer.py`: storing it exactly once

```python
key = (r.date, r.amount_minor, desc.upper()); occurrence = seen[key]; seen[key] += 1
fp = fingerprint(account_id, r.date, r.amount_minor, desc, occurrence)
INSERT OR IGNORE INTO transactions (..., fingerprint)      -- UNIQUE(fingerprint)
```

`rowcount == 1` means new, `0` means duplicate. Everything runs inside `with transaction(conn)`, so a
failure mid-file leaves no half import (`test_unlearnable_format_is_refused_not_guessed`).

### 5. `categorize/pipeline.py`: the cascade

`process_pending` → `_start_run` (new, or resume with the stored checkpoint) → loop over batches:

```python
snapshot = RunStats(**asdict(stats))
with transaction(conn):
    _process_batch(...)                  # category writes
    UPDATE runs SET checkpoint_id, stats  # same transaction
# BudgetExceeded → rolled back → stats = snapshot → status paused_budget
```

Inside `_process_batch`, our rent row:
1. `looks_like_injection`: no.
2. `first_match(rules, "RAMESH KUMAR", …)`: no rules yet on first import.
3. Sent to `categorize_batch` with the other unresolved rows.

### 6. `categorize/llm_categorizer.py`: the model call

- `retrieve_examples`: same-merchant verified labels first (`WHERE id IN (SELECT MAX(id) … GROUP BY merchant, direction)`),
  then recent ones.
- `build_input` produces the prompt layout (stable → volatile): `<user_profile>` (the household block says
  *"Landlord is Ramesh Kumar"*), `<verified_examples>`, `<transactions>` as redacted JSON. Our row's
  description becomes `UPI/DR/[num-1458]/RAMESH KUMAR/SBIN/[vpa]@oksbi/rent`.
- `llm.parse(schema=CategorizationBatch)`: `category` is the `Category` Literal, so the SDK builds a
  strict JSON schema with an enum.
- Items the model skipped are retried once. Returned: `{txn_id: TxnCategory}`.

Back in the pipeline: `direction_ok("Housing:Rent", -3200000)` is true, confidence 0.93 ≥ 0.80, so
`status='categorized', category_source='llm'`.

### 7. `llm/client.py`: what happened during that call

`OpenAIClient.parse`:
1. **Cache key** = sha256(model, effort, instructions, input, schema). A hit returns the stored JSON and logs `cache_hit=1`.
2. `meter.check()` raises `BudgetExceeded` *before* spending.
3. `client.responses.parse(..., text_format=schema, store=False, reasoning={"effort": "low"})`. The SDK retries
   429/5xx/timeouts (`max_retries`) with exponential backoff.
4. `status == "incomplete"` or `output_parsed is None` (a refusal) becomes `LLMError`, which the pipeline turns into a review.
5. `_audit` writes one `llm_calls` row: purpose, tokens, latency, cost (if prices are configured), error.

### 8. `categorize/review.py`: when a human disagrees

Suppose the model had said `Transfers:To People` for the rent (no household memory). You answer
`Housing:Rent` in `ledger review`, and `set_category` does all of this in one transaction:
- the transaction becomes `user`-sourced, confidence 1.0
- `INSERT INTO labels` with `old_category='Transfers:To People'`, `kind='correction'`
- the model's *other* `Transfers:To People` answers for RAMESH KUMAR are flagged `sibling_of_correction`
- `invalidate_conflicting` (no rule yet) and `compile_from_labels` (needs 2 agreeing labels, so none yet)

Next month, the rent row meets `retrieve_examples` (same merchant) and the model gets it right. When you
confirm it, the second label compiles `merchant = RAMESH KUMAR, debit → Housing:Rent`, and from month
three on the rule resolves it before the model is asked. `test_compiled_rule_means_no_more_llm_calls_for_that_merchant`
proves exactly this.

`audit_sample` is the other entry point. Read its SQL: group model-labelled rows by (merchant, category),
skip merchants with any verified label, and order by `n * (1.05 - avg_confidence)`.

### 9. `insights/`: from rows to insight

- `recurring.detect_recurring`: per merchant, median interval → cadence (weekly/monthly/quarterly/yearly with
  tolerances), ≥ 75% of intervals regular, amount MAD/median ≤ 15%. `price_change_pct` compares the last charge
  with the median of the earlier ones. That's how Netflix's ₹649 → ₹799 shows up as +23.1%.
- `report.month_facts`: SQL only. `write_report` → `llm.parse(ReportNarrative)` → `ungrounded_numbers`
  → feedback retries → `_strip_ungrounded` → `render_markdown` (tables come from facts, never from the model).

---

## Part 2: follow a question

`ledger ask "How much did I spend on food delivery in July?"`

1. `cli.cmd_ask` → `LedgerService.ask`, which sets a per-question token budget (`_budget`).
2. `agent/loop.ask`:
   - `build_instructions` = `SYSTEM` + today + `memory.render_blocks` + `memory.recall(question)`.
     `recall` scores facts with BM25 (tokenized, stopwords removed), `0.995^hours` recency and importance/10,
     and leaves out irrelevant low-importance facts entirely.
   - `load_history(conversation_id, 6)` gives the previous Q/A pairs as plain messages.
3. Step 1: `llm.step(...)` → `responses.create(tools=tool_specs(), store=False,
   include=["reasoning.encrypted_content"])`. The model returns a `function_call`:
   `spending_summary(start_date="2026-07-01", end_date="2026-07-31", group_by="category", direction="debit")`.
   `step.output_items` (reasoning item + function call) are appended to `items` **verbatim**.
4. `tools.execute` → handler → text table with ₹ amounts and a TOTAL row. It never raises; `ToolError`, `TypeError`
   and `sqlite3.Error` become `"Error: …"` strings with `is_error=True`. The output is truncated to
   `tool_output_max_chars` with a hint to narrow the query.
5. `{"type": "function_call_output", "call_id": …, "output": …}` is appended; `_clear_old_outputs` runs.
6. Step 2: the model answers in text, and the loop ends with `stop="done"`. Only `(question, answer)` goes to
   `conversation_turns`.

If the model had written `run_sql("DELETE FROM transactions")`: `sql_guard.run_readonly` opens a
**separate read-only connection** (file DBs), installs the authorizer (`SQLITE_DELETE` isn't in
`_ALLOWED_ACTIONS` → `SQLITE_DENY`), and SQLite refuses at *prepare* time. The agent receives
`"Error: query not allowed…"` and carries on. `test_everything_else_is_denied` covers eleven variants.

---

## Part 3: follow a click (the web UI)

Open `ui/src` next to this section. You press **Enter** on the Review page:

1. `pages/Review.tsx` has a window `keydown` listener. It ignores keys typed into inputs and keeps Enter for
   focused buttons, then calls `accept()`. Suspicious entries can't be accepted with one keystroke; the button is
   disabled and the listener refuses too.
2. `commit()` calls `api.accept(id)`. `lib/api.ts` adds the bearer token if one is stored, turns a FastAPI
   `{"detail": …}` into an `ApiError` with that message, and turns a network failure into plain words.
3. The server runs `review.set_category` (Part 1, step 8) and returns a `CorrectionResult`, now including
   `siblings_flagged`.
4. The card gets `is-stamped`, and the `Stamp` presses in (`stamp-press` keyframes, 160ms), unless the reader
   prefers reduced motion, in which case the wait is zero.
5. A slip explains any side effect you would otherwise find surprising: "Rule learned for RAMESH KUMAR · 2 more
   entries were posted with it", or "2 earlier answers for AIRTEL sent back for review". A number that changes
   without explanation feels like a bug, so every side effect of a correction gets a sentence.
6. The queue is **re-read from the server** (not patched locally), because one answer can compile a rule that
   removes other entries from the queue, or flag siblings that add entries.

Design tokens: every color and size used above comes from `styles/tokens.css`, which mirrors the approved
`DESIGN.md`. The one place the UI decides a *meaning* is `components/Ledger.tsx`: `CategoryLabel` turns
`category_source` into blue pencil (model), a RULE stamp (rule) or ink plus "You" (you). That's the backend's
trust hierarchy (THEORY §1), made visible.

## Part 4: reading the tests as documentation

| Test file | Read it to understand |
|---|---|
| `test_parsing.py` | the messy-input contract: amounts, dates, merchants, redaction |
| `test_ingest.py` | profiles, the balance sensor, dedup, learning a new format with feedback, refusing to guess |
| `test_pipeline.py` | cascade order, every routing reason, budget pause/resume, redaction in prompts |
| `test_learning.py` | the memory lifecycle: label → example → rule → propagation → forgetting → audit |
| `test_sql_guard.py` | what the agent's SQL can and can't do |
| `test_agent.py` | loop mechanics, tool errors, memory persistence, history, least-privilege proposals |
| `test_insights.py` | recurring detection, fact correctness vs ground truth, the number verifier |
| `test_llm_client.py` | caching, budgets, audit rows, error mapping, Responses-API tool-call parsing |
| `test_api.py` | the HTTP surface, auth, error mapping, UI read endpoints, serving the built UI (SPA fallback, caching, no traversal) |
| `ui/src/**/*.test.ts(x)` | money formatting, safe rendering of model text, API client, combobox keyboard flow, charts, keyboard review flow |

## Exercises

1. **Structured claims.** Make `ReportNarrative` return `claims: [{metric, category, value}]` and verify each against the facts (THEORY §8).
2. **Self-consistency confidence.** Call the categorizer 3 times at higher temperature and use agreement as confidence. Compare the silent-error rate at equal automation.
3. **Split transactions.** Add a `splits` table and a `split(txn_id, [(category, amount)])` operation that keeps totals exact.
4. **PDF import.** Add a `pdf_reader.py` that extracts tables into a `RawTable`. Everything downstream just works.
5. **Uniform audit estimator.** Add `ledger audit --uniform 50` that estimates the silent-error rate with a Wilson interval.
