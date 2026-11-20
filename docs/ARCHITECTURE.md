# Architecture

## Component map

```
                                      ┌──────────────┐
   browser ─────────────────────────▶ │  web UI      │  ui/ (React + TS), built into ledger_agent/static,
                                      │  (static)    │  served by api.py from "/" (SPA fallback)
                                      └──────┬───────┘
                ┌──────────────┐      ┌──────▼───────┐
   user ───────▶│  cli.py      │      │  api.py      │◀─────── HTTP clients
                └──────┬───────┘      └──────┬───────┘
                       └──────────┬──────────┘
                           ┌──────▼───────┐   one facade: wiring, per-operation budgets
                           │  service.py  │
                           └──────┬───────┘
      ┌──────────────┬────────────┼──────────────┬───────────────┬─────────────────┐
┌─────▼─────┐  ┌─────▼──────┐ ┌───▼─────────┐ ┌──▼─────────┐ ┌───▼─────────┐ ┌─────▼──────┐
│ ingest/   │  │categorize/ │ │ agent/      │ │ insights/  │ │ memory.py   │ │ datagen.py │
│ csv/pdf   │  │ pipeline   │ │ loop        │ │ recurring  │ │ blocks      │ │ demo+eval  │
│ profiles  │  │ rules      │ │ tools       │ │ report     │ │ facts       │ │ data       │
│ normalize │  │ llm_categ. │ │ sql_guard   │ │            │ │             │ │            │
│ merchant  │  │ review     │ │             │ │            │ │             │ │            │
│ importer  │  │            │ │             │ │            │ │             │ │            │
└─────┬─────┘  └─────┬──────┘ └───┬─────────┘ └──┬─────────┘ └───┬─────────┘ └────────────┘
      │              │            │              │               │
      │       ┌──────▼────────────▼──────────────▼──┐            │
      │       │ llm/client.py  (the ONLY OpenAI caller) │          │
      │       │ parse() structured · step() tools      │          │
      │       │ retries · cache · budget · audit log   │          │
      │       └──────────────────┬─────────────────────┘          │
      │                          │ security/redact.py (PII + untrusted text) on the way in
┌─────▼──────────────────────────▼────────────────────────────────▼──────┐
│ db.py: SQLite (WAL), versioned migrations, transaction() helper        │
└──────────────────────────────────────────────────────────────────────────┘
```

Dependency rule: arrows point down only. `llm/client.py` knows nothing about bookkeeping, and
bookkeeping modules depend on the `LLMClient` *protocol*, never on the OpenAI SDK. That's what lets
`FakeLLM` stand in for tests, CI and offline evals.

## Data model

| Table | Holds | Notes |
|---|---|---|
| `accounts` | bank accounts / cards | |
| `import_profiles` | learned CSV layouts, keyed by header signature | **procedural memory** |
| `imports` | one row per imported file: counts, balance check | audit trail |
| `transactions` | the ledger | `amount_minor` INTEGER paise; `fingerprint` UNIQUE; `category_source` ∈ rule/llm/user; `status` ∈ pending/categorized/needs_review |
| `rules` | user and compiled rules | `active` flag gives forgetting without deletion |
| `labels` | every human decision (+ what the model had said) | **episodic memory**, written by humans only |
| `runs` | processing runs, checkpoint, stats, status | resumability |
| `llm_calls` | every model call: purpose, model, tokens, cost, latency, cache hit, error | observability & cost |
| `llm_cache` | content-addressed structured responses | idempotent re-runs |
| `memory_blocks` | household / preferences / goals | **core memory** (pinned) |
| `memory_facts` | long-term facts | **semantic memory** (retrieved) |
| `conversation_turns` | Q/A pairs per conversation | **episodic** (chat) |
| `receipts` | bill photos / invoice PDFs, the model's reading (total, line items), and the entry each is pinned to | evidence only: never adds money; one bill per entry |
| `v_transactions` (view) | the only surface the agent's SQL tool may read | amounts in rupees |

## Operation flows

### Import

```
bytes ─▶ decode (utf-8/utf-16/cp1252) ─▶ sniff delimiter ─▶ find header row (keyword score, fallback shape rule)
      ─▶ signature = hash(normalized header)
      ─▶ profile: stored? ─▶ validate ─▶ ok → use (0 tokens)
                  heuristic ─▶ validate ─▶ ok → save
                  LLM propose ─▶ validate ─▶ fail → feedback → retry (≤3) ─▶ save | refuse import
      ─▶ parse rows (Decimal → paise) ─▶ fingerprint (with per-file occurrence) ─▶ INSERT OR IGNORE
      ─▶ merchant + channel extraction (deterministic)          [all inside ONE transaction]
```

PDF statements take one extra step at the front (`ingest/pdf_reader.py`): text is extracted in layout mode,
split into cells at runs of 2+ spaces, cells are assigned to the header's columns (numbers by their right edge),
wrapped narrations are rejoined, and repeated page headers and footers are dropped. The result is the same
`RawTable` the CSV reader returns, so profiles, the balance check and dedupe are shared. A locked PDF is opened
with the password sent with the upload, which is then dropped.

### Bill (receipt)

```
photo / PDF ─▶ sniff type ─▶ same bytes seen? → return it (no model call)
            ─▶ llm.parse(ReceiptRead): image item for photos, redacted text for PDFs with a text layer
            ─▶ sensors: is_receipt, total > 0, items add up (±₹1)
            ─▶ match: debit of exactly the total, ±3 days, not already explained; several → payee-name overlap;
                      still tied → unmatched, with the nearest entries offered to a person
            ─▶ INSERT receipts (matched | unmatched); a person can pin/unpin (match_status = user)
```

### Process (one run)

```
run = new or resumed (checkpoint id)
loop:
  batch = next 20 pending rows after checkpoint
  BEGIN
    per row: injection tripwire? → review
             rule match?         → categorized (rule)
             mirrored by an equal, opposite entry in another own account (±4 days, unique both ways)?
                                 → Transfers:Self (rule); the other side follows unless a human or rule decided it
    rest → retrieve verified examples → build redacted prompt → llm.parse(CategorizationBatch)
         → per item: missing → review · direction sensor fails → review · conf < τ → review · else categorized (llm)
    UPDATE runs SET checkpoint, stats
  COMMIT                          (BudgetExceeded → ROLLBACK batch, status paused_budget)
```

### Correct (review or audit answer)

```
BEGIN
  txn := user category (confidence 1.0)
  INSERT label (old model answer, new category)
  if it overturned a model answer: flag the model's identical sibling answers → review
  deactivate compiled rules that disagree
  if last N labels for (merchant, direction) agree: compile rule → propagate to unverified rows
COMMIT
```

### Ask

```
instructions = SYSTEM + date + memory blocks + recalled facts(question)
items = history(last 6 Q/A) + question
repeat ≤ 12: step = llm.step(instructions, items, tools)
             no tool calls → answer
             else execute each (never raises) → function_call_output (truncated) → clear old outputs if large
persist (question, answer)
```

## Design decisions (and rejected alternatives)

| Decision | Alternatives considered | Why this one |
|---|---|---|
| SQLite, one file | Postgres from day 1 | single-user tool, zero ops, transactional, WAL gives concurrent reads. `db.py` is the only place that knows it's SQLite, and the scaling path is in OPERATIONS.md |
| Closed category enum | free-text categories + normalization | makes invalid output impossible; injection-resistant; reports stay consistent. Extending means editing one list |
| Cascade: rules → LLM → human | LLM for everything | cost falls over time; rules are auditable; the model only handles what's actually unknown |
| Own-account transfers matched by amount and date across accounts | household memory or prompt instructions | the model reads one line at a time and was confidently wrong on card bills; a pairing check needs no tokens and can't be talked out of it |
| Learning by compiling rules | fine-tuning; only few-shot | instant, free, explainable, reversible; fine-tuning a model per user isn't |
| Human-only writes to `labels` | writing confident model answers as labels | avoids self-reinforcing errors (THEORY §5.1) |
| Audit sampler + sibling flags | trust confidence; review everything | the only way to catch confident errors at a fixed small human cost |
| Structured outputs via `responses.parse` + Pydantic | JSON mode + manual parsing | schema-enforced decoding; typed results; refusals and incomplete outputs become explicit errors |
| Responses API, `store=False`, encrypted reasoning replay | `previous_response_id` server-side state | the client owns the history: privacy, portability, and exact control of the context |
| Agent can only *propose* recategorizations | agent edits directly | least privilege: a prompt-injected or confused agent can't corrupt the books |
| Model writes words, SQL writes numbers, code verifies | model writes the whole report | fluent wrong numbers are the worst failure in finance |
| Content-addressed LLM cache | none | rolled-back batches, retries and evals re-run for free and reproducibly |
| One service instance per HTTP request | shared global connection | no transaction interleaving between requests on one SQLite connection |
| UI built into the Python package, served by FastAPI | separate frontend server / CDN | one process, one port, one artifact: `pip install` or the Docker image gives you the whole app; no CORS |
| React SPA with a hand-written typed client | generated client; server-rendered pages | the API is small and stable; a 60-line client is easier to read than a generator's output. Keyboard-first review needs client-side state |
| No UI component or chart library | MUI / Tailwind / Recharts | the design system (DESIGN.md) is the product's identity; ~20 small components cover it, and charts follow the validated palette and dataviz rules exactly |
| Bills are evidence pinned to an entry, not entries | importing a bill as a transaction | the payment is already in the statement; a second entry would double-count it. Matching needs the exact amount, so a misread total fails safe (unmatched) |
| PDF statements rebuilt into the CSV reader's table | a separate PDF parsing path; an LLM reading the PDF | one validator for both formats; no tokens; the balance check catches a bad column rebuild |
| Model text rendered by a tiny safe renderer | a markdown library with raw HTML | narrations are attacker-controlled and can reach answers; no HTML path exists |

## Extension points

- **New bank formats**: nothing to code. The profile learner handles them, or add header synonyms to `heuristic_profile`.
- **New categories**: edit `categories.py`. Schemas, tools and validation pick them up.
- **Better confidence**: replace the self-reported field in `llm_categorizer.py` with self-consistency
  (`n` samples, agreement rate), keeping the pipeline unchanged.
- **Embeddings for facts/examples**: replace `memory.recall` / `retrieve_examples` scoring. Interfaces stay the same.
- **Another provider**: implement `LLMClient` (`parse`, `step`, `meter`). Nothing else changes.
