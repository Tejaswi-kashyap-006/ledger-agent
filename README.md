# Ledger Agent

**An AI bookkeeper for messy Indian bank statements.** Import CSV exports or PDF e-statements (password-locked
ones too) from any bank or card, and photograph shop bills. It learns the file format, categorizes every transaction, learns from your corrections until it barely
needs the model, catches its own confident mistakes, reconciles balances, finds subscriptions and price
hikes, pins each bill to the payment it explains (with its line items split by category), writes a monthly
report whose numbers are checked, and answers questions like *"how much did we spend eating out in July?"*

It's the capstone of a ten-project course on agent harness engineering (the loop, the harness, context,
memory, long-horizon runs, multi-agent, evals): every idea from those projects, P01-P10, applied to one
real problem, with the
production concerns that tutorials usually skip (money correctness, idempotency, budgets, privacy,
prompt injection, audit logs, evals in CI). **One process serves both the web app and its REST API.**

![Overview, day theme](docs/images/overview-light.jpg)

| Review: the model's guess in blue pencil, one keystroke to initial it | The ledger: who decided each category is always visible |
|---|---|
| ![Review, lamplit theme](docs/images/review-dark.jpg) | ![Ledger, lamplit theme](docs/images/ledger-dark.jpg) |

```
statement.csv ─▶ read & find table ─▶ learn/reuse import profile ─▶ parse + validate ─▶ dedupe ─▶ SQLite
                                        (procedural memory)          (balance sensor)
pending txns ─▶ injection tripwire ─▶ rules + own-account transfer match ─▶ LLM (structured, few-shot) ─▶ sensors
                   │                   │ 0 tokens                           │ confidence ≥ 0.8 and direction ok
                   ▼                   ▼                 ▼
               human review ◀── low confidence / flags   categorized ──▶ audit sample (spot-check) ──▶ human
                   │
                   └─▶ correction ─▶ verified label ─▶ few-shot example ─▶ compiled rule ─▶ propagates
```

## Why this problem

- **Real and universal.** UPI narrations look like `UPI/DR/412345678901/RAMESH KUMAR/SBIN/ramesh.kumar@oksbi/rent`.
  Every bank exports a different CSV layout. Nobody categorizes by hand for long.
- **Correctness is checkable.** Balances must reconcile to the paisa, which gives you hard sensors
  that most agent demos lack.
- **The model is the least trusted component.** It proposes; deterministic code, verified memory and
  humans decide. That's harness engineering in its clearest form.
- **Memory has measurable value.** Human workload goes down month over month, and the evals show it.

## Quickstart

**See the app in two minutes (no API key needed):**

```powershell
cd ledger-agent
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ui; npm install; npm run build; cd ..       # builds the web UI into the package
python scripts/seed_demo_db.py data/demo.db    # 3 months, 2 accounts, 2 bills pinned, categorised offline
$env:LEDGER_DB_PATH = "data/demo.db"
ledger serve                                   # open http://127.0.0.1:8000
```

**Use it for real (OpenAI):** put `OPENAI_API_KEY=sk-...` in a `.env` file in this folder (it's git-ignored), or:

```powershell
$env:OPENAI_API_KEY = "sk-..."
Remove-Item Env:LEDGER_DB_PATH                 # back to your own ledger at data/ledger.db
ledger serve                                   # then: Import → Review → Overview → Ask
```

**A five-minute demo** on the seeded database, with a key set (about 5 model calls, under 10k tokens):

1. **Import** `sample_data/hdfc_savings_2026-09.pdf` as *HDFC Savings*: a two-page PDF e-statement with wrapped
   narrations comes back with 28 new rows and a RECONCILED stamp. Then *Categorise them now*.
2. **Bills**: drop `sample_data/receipts/bigbasket_2026-08-18.png` (a photo) and `amazon_invoice_2026-08-16.pdf`.
   Each is read, checked to add up, and pinned to its August payment. The invoice splits one ₹1,299 card payment
   into *Education* (the book) and *Shopping · Electronics* (the case and its GST).
3. **Review**: the Apollo Pharmacy entry now shows what its bill says (₹581 of medicine, ₹309 of personal care).
4. **Ledger**: entries with a bill carry a BILL stamp; card bill payments carry RULE (matched transfers).

Everything in the UI is also available from the terminal (`ledger import`, `process`, `review`, `audit`, `ask`,
`report`, `subs`, `stats`), and over HTTP (docs at `/docs`).

**Check it:**

```powershell
pytest                                         # backend: 115 tests, offline
python evals/run_evals.py --fake               # offline eval: learning curve, safety, grounding
cd ui; npm run typecheck; npm test             # frontend: strict TS + 44 tests
```

## The web app

A designed interface, not a dashboard kit: the app is laid out like a *bahi-khata*, the red account book
Indian traders keep (see [DESIGN.md](DESIGN.md) for the approved design system and [ui/README.md](ui/README.md)
for the code). The trust model of the backend is visible in the interface:

| On screen | Means |
|---|---|
| *blue pencil handwriting* | the model's suggestion, not yet in the books |
| black ink + **RULE** stamp | posted by a deterministic rule (learned from you, or written by you) |
| black ink + **✓ YOU** | your decision, the ground truth |
| haldi (turmeric) highlighter | needs your attention |
| green **RECONCILED** stamp | the statement's running balance checked out to the paisa |

| Page | What it's for |
|---|---|
| **Overview** | the month's folio: net figure, *Jama · Naam* (in · out), where it went, trend, what's waiting |
| **Import** | drop CSV or PDF statements (a password field appears for locked PDFs); each comes back as a receipt with new / duplicate / rejected rows and the balance stamp |
| **Bills** | "The bill spike": drop bill photos or PDF invoices; each is read, checked to add up, and pinned to the payment it explains, split by category |
| **Review** | one entry at a time. `Enter` initials the suggestion, `1`–`9` quick categories, `/` search, `S` skip |
| **Audit** | spot-check the model's *confident* answers (the only way to catch silent errors) |
| **Ledger** | every entry, filterable; correct any category in place (it teaches the book like Review does) |
| **Ask** | "Ask the munim": questions answered by the tool-using agent, with the tools it consulted as footnotes |
| **Reports** | the monthly folio; every figure is verified against the books, and invented ones are struck from the record |
| **Recurring** | subscriptions, EMIs, rent; price rises flagged |
| **Settings** | memory blocks, remembered facts, rules, the access key, model usage |

Day and lamplit (dark) themes, keyboard-first review, screen-reader labels on amounts and charts, reduced
motion respected, and it works down to 390px wide.

## Commands

| Command | What it does |
|---|---|
| `ledger import FILE... --account NAME [--password PW]` | CSV or PDF: read, learn or reuse the format profile, validate (parse rate + running balance), dedupe, store |
| `ledger process [--resume RUN] [--limit N]` | run the categorization cascade in checkpointed batches under a token budget |
| `ledger review` | human review queue (low confidence, sensor flags, suspicious text, errors) |
| `ledger audit [--n 5]` | spot-check confident model answers: the only way to catch silent errors |
| `ledger ask ["question"]` | Q&A agent (tools + read-only SQL sandbox + memory); no question = chat |
| `ledger report YYYY-MM [--out f.md]` | monthly report: SQL facts + LLM narrative + number verifier |
| `ledger rules [--add 'ZOMATO=Food:Delivery']` | list/add deterministic rules (user rules outrank compiled ones) |
| `ledger subs` | recurring payments, monthly cost, price changes, next expected date |
| `ledger memory [--set 'block=text']` | view/edit pinned memory (household / preferences / goals) and facts |
| `ledger stats` | automation rate, review backlog, rules, LLM calls/tokens/cost by purpose, recent runs |
| `ledger demo` / `ledger serve` | sample statements (CSV + one PDF) / the web app + HTTP API |

HTTP API (interactive docs at `/docs`): `POST /v1/imports` (CSV or PDF, optional `password`), `POST|GET /v1/receipts`, `GET|DELETE /v1/receipts/{id}`, `GET /v1/receipts/{id}/file`, `POST /v1/receipts/{id}/attach`, `POST /v1/process`, `GET /v1/review`, `GET /v1/audit`,
`POST /v1/transactions/{id}/category|accept`, `GET /v1/transactions`, `GET|POST|DELETE /v1/rules`, `POST /v1/chat`,
`GET /v1/conversations/{id}`, `GET /v1/reports/{month}?format=md`, `GET /v1/facts/{month}`, `GET /v1/trend`,
`GET /v1/months`, `GET /v1/accounts`, `GET /v1/categories`, `GET /v1/subscriptions`, `GET|PUT /v1/memory/blocks[/{label}]`,
`GET|DELETE /v1/memory/facts[/{id}]`, `GET /v1/stats`, `GET /healthz`. Set `LEDGER_API_KEY` to require a bearer token.

## Measured (offline keyword model, `python evals/run_evals.py --fake`)

| month | automation | auto accuracy | silent errors | human reviews + audits | rule / model |
|---|---:|---:|---:|---:|---:|
| 2026-06 | 82% | 91% | 7.7% | 8 + 5 | 2 / 30 |
| 2026-07 | 98% | 100% | 0.0% | 1 + 5 | 6 / 35 |
| 2026-08 | 100% | 100% | 0.0% | 0 + 5 | 8 / 32 |

Without audits (`--audit 0`), silent errors stay around 7.5% every month: the keyword model files
"THIRD WAVE CO**FFEE**" under *Fees* with high confidence, and no uncertainty-based queue ever surfaces
it. See [docs/THEORY.md §4](docs/THEORY.md).

Card bill payments are matched deterministically: a debit in one of your accounts with an equal and
opposite credit in another within 4 days (and no other candidate) is posted as *Transfers:Self* without the
model. In a live run without household memory, `gpt-5.4-mini` had filed the bill under *Loans & EMI* at
0.95 confidence, which inflated spending; see `categorize/transfers.py`. Run the same eval against OpenAI (drop `--fake`) to also
get Q&A pass@1 and pass^3.

## Configuration

Everything is an env var with the `LEDGER_` prefix (or a `.env` file); see `.env.example` and
`src/ledger_agent/config.py`. The most important ones: `OPENAI_API_KEY` (the environment or `.env`; the environment wins), `LEDGER_MODEL_BULK`
(default `gpt-5.4-mini`), `LEDGER_MODEL_AGENT` (default `gpt-5.4`), `LEDGER_AUTO_ACCEPT_CONFIDENCE`
(0.80), `LEDGER_MAX_TOKENS_PER_RUN`, `LEDGER_PRICE_INPUT_PER_MTOK` / `..._OUTPUT_...` (enable $
tracking), and `LEDGER_API_KEY`.

## Documentation

| Doc | For |
|---|---|
| [DESIGN.md](DESIGN.md) · [docs/UI_DESIGN_PROTOCOL.md](docs/UI_DESIGN_PROTOCOL.md) · [ui/README.md](ui/README.md) | the approved design system; the UI rules behind it; the frontend code |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | components, data flow, schema, design decisions and rejected alternatives |
| [docs/THEORY.md](docs/THEORY.md) | the expert theory: cascades, calibration, silent errors, memory lifecycle, exactly-once, injection, grounding |
| [docs/CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md) | a guided read of the code: trace one transaction and one question end to end |
| [docs/EVALS.md](docs/EVALS.md) | metrics, ablations, the CI gate, how to add eval tasks |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | deploy, monitor, runbooks, cost control, scaling path |
| [docs/SECURITY.md](docs/SECURITY.md) | threat model, data flows to the LLM provider, controls and known gaps |

## Where each course project shows up

P01-P10 are the course's projects, which the docs here refer to by number. The course itself lives
outside this repository; this table is the map from each idea to its code.

| Course project | In Ledger Agent |
|---|---|
| P01 loop | `agent/loop.py`: Responses-API tool loop |
| P02 harness | `llm/client.py` (retries, budgets, audit log, cache), `agent/tools.py` (strict schemas, errors as observations, truncation) |
| P03 tools/sensors | `agent/sql_guard.py` (sandbox), balance reconciliation, direction sensor, number verifier |
| P04 context | lean per-question context, history of answers only, old tool outputs cleared, stable-prefix prompts |
| P05 memory blocks | `memory.py` household / preferences / goals blocks, editable by the agent |
| P06 long-term memory | `memory.py` facts with BM25 + recency + importance recall; verified labels as episodic memory |
| P07 procedural memory | import profiles and compiled rules: skills learned once and reused for free |
| P08 long-horizon | `categorize/pipeline.py`: checkpointed, budgeted, resumable runs |
| P09 multi-agent | evaluator-optimizer for reports with a *code* evaluator; humans as the second agent |
| P10 evals | `evals/run_evals.py`: learning curves, ablations, safety checks, pass^k, CI regression gate |

## Limitations and roadmap

- PDF statements need a text layer. Scanned statements are refused with a clear message; a vision step for them
  would slot in before `read_pdf_table`. The column rebuild is tested on generated layouts, so a bank's unusual
  PDF may need its header synonyms added; the balance check makes a bad rebuild fail loudly, never silently.
- Bills are evidence: their line-item split is shown, not booked. Booking one payment under two categories
  (split transactions) isn't modelled yet. Bill photos go to the model provider unredacted (SECURITY.md).
- Single user, SQLite. The path to multi-user is in [OPERATIONS.md](docs/OPERATIONS.md#scaling-path).
- Keyword BM25 for fact recall. Swap in embeddings (`sqlite-vec`) once you have hundreds of facts.
- The model's confidence isn't calibrated. The threshold is a knob you should tune with the eval (THEORY §3).
