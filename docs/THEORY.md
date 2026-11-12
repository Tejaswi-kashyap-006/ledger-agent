# Ledger Agent: the theory

This document explains *why* Ledger Agent is built the way it is. Each section starts from a general
principle of agent and harness engineering, gives the reasoning (and the math where it helps), and then
points to the code that implements it. Read it with [ARCHITECTURE.md](ARCHITECTURE.md) open.

---

## 1. The trust hierarchy: "the model proposes, the harness decides"

An agent is `Model + Harness`. The model is the most capable component, and also the least reliable
one: it's non-deterministic, it can't be unit tested, it can be manipulated through its inputs, and
it's confidently wrong in ways that don't announce themselves. So Ledger Agent ranks every source of
truth and never lets a lower rank override a higher one:

| Rank | Source | Examples | Why trusted |
|---|---|---|---|
| 1 | **Deterministic code** | balance reconciliation, schema enums, SQL authorizer, number verifier | provably correct for what it checks |
| 2 | **Human decisions** | review answers, audit answers, user-authored rules | the user *defines* the ground truth for their own books |
| 3 | **Verified memory** | labels, compiled rules, import profiles | derived only from ranks 1-2 |
| 4 | **The model** | category suggestions, import-profile proposals, narratives, answers | useful, never authoritative |

Every design decision below follows from this table. For example:
- The model's categorization is **stored as a suggestion with a source (`llm`)**, so a later rule or a human can
  overwrite it and reports can show what's unverified.
- The agent **can't write the ledger**. `propose_recategorization` puts items in the human queue, and it
  skips rows a human already verified (rank 2 beats rank 4).
- Memory is written **only from ranks 1-2** (§5). Otherwise the model would teach itself its own mistakes.

This is Fowler's guides/sensors framing applied to data rather than code: *guides* (schemas, few-shot
examples, pinned memory) raise the chance the model is right, and *sensors* (reconciliation, direction
check, verifier, audits) find out when it isn't.

---

## 2. Tiered inference: why a cascade

### 2.1 The cascade

Each pending transaction goes through tiers ordered from cheapest and most trusted to most expensive
and least trusted:

```
tripwire (regex) ─▶ rules (dict lookup) ─▶ LLM (batched, structured) ─▶ sensors ─▶ accept | human
```

Let `p_r` be the fraction resolved by rules, `p_m` the fraction the model resolves confidently, and
`p_h = 1 - p_r - p_m` the fraction sent to a human. With per-item costs `c_r ≈ 0`, `c_m` (tokens) and
`c_h` (human attention, which is by far the largest), the expected cost per transaction is

```
E[cost] = p_r·c_r + (1 - p_r)·c_m + p_h·c_h
```

Two consequences drive the design:

1. **Every point of rule coverage removes a model call entirely.** The learning loop (§5) exists to
   push `p_r` up over time. In the eval, rule coverage rises from 0 to 6 of 40 transactions a month
   within two months, and token use per transaction falls accordingly (it would fall much faster for a
   real household with more repeat merchants).
2. **`c_h` dominates.** Thresholds are set to minimize *human time plus the cost of errors*, not tokens
   (§3).

### 2.2 Batching

Categorization sends 20 transactions per call. Batching amortizes the fixed prompt (instructions,
profile, examples: roughly 1-2k tokens) across the batch, so the per-item cost is roughly
`fixed/B + per_item`. Larger `B` is cheaper, but:
- attention dilutes, and item-level accuracy degrades on long lists (context rot, P04)
- the **blast radius** of one failure grows (a failed call sends `B` items to review)
- the model skips items more often, which is why `categorize_batch` checks every `idx` is covered and
  retries the missing ones once

`B = 20` is a reasonable default. Tune it with the eval: accuracy and tokens per transaction against `B`.

### 2.3 Why structured outputs are a *control*, not a convenience

The output schema's `category` field is the closed `Category` enum (`categories.py`). With strict
structured outputs the model **can't** emit an invalid category, a free-form sentence, or text copied
from an injection. That turns "please only answer with one of these" (a guide the model may ignore)
into a guarantee enforced during decoding. It's the strongest guardrail in the system, and it costs nothing.

---

## 3. Selective prediction: the confidence threshold

The pipeline auto-accepts a model answer only when `confidence ≥ τ` (default 0.80) *and* the
direction sensor agrees. This is **selective prediction**: trade *coverage* (how much you automate)
against *risk* (the error rate among what you automate).

### 3.1 The risk-coverage trade-off

Sort model answers by confidence. For each threshold `τ`:
- coverage `C(τ)` = fraction with confidence ≥ τ
- selective risk `R(τ)` = error rate within that fraction

Raising `τ` lowers `C` and (if confidence carries any signal) lowers `R`. Choose `τ` to minimize the
real cost:

```
cost(τ) = (1 - C(τ))·c_review  +  C(τ)·R(τ)·c_silent_error
```

where `c_silent_error` (a wrong number in your books that nobody noticed) is usually several times
`c_review` (a few seconds of your attention). **Tune τ with the eval, not by intuition.** Record
(confidence, correct) pairs per model answer and sweep τ.

### 3.2 Verbalized confidence is poorly calibrated

The `confidence` field is the model's *self-report*. LLM self-reported confidence is informative but
**miscalibrated**: it clusters at 0.8-0.95 whatever the actual accuracy. Calibration is measured by
Expected Calibration Error, which bins predictions by confidence and averages the gap between the
bin's accuracy and its mean confidence. Practical consequences:
- The threshold is a relative cut, not a probability. Re-tune it when you change the model or the prompt.
- Better confidence signals, in increasing cost: token logprobs of the category, **self-consistency**
  (sample `k` answers and use the agreement rate), and a second cheap model as a verifier (disagreement goes to review).
- Deterministic sensors add information the model doesn't have. The **direction sensor** (`pipeline.direction_ok`)
  catches "Income:Salary on a ₹450 debit" whatever confidence the model claims.

---

## 4. Silent errors and sampling sensors

### 4.1 The blind spot of uncertainty-based review

A review queue fed by *low confidence* only ever shows humans the cases the model *knew* were hard.
Errors the model makes **confidently**, the *silent errors*, never reach a human, so they never become
corrections, so memory never learns from them. They repeat every month. The eval shows this directly:
with `--audit 0`, the keyword model's "THIRD WAVE CO**FFEE** → Fees" mistake is auto-accepted at 0.85
confidence in all three months, holding silent errors at ~7.5%.

Worse, errors are **systematic**, not random. A model that is wrong about a merchant is wrong about it
every time. Silent errors therefore cluster by merchant, and so does the damage.

### 4.2 The audit sampler

`review.audit_sample` is a **sampling sensor**. It spot-checks *confident* model answers:
- one row per (merchant, category) group, because errors cluster by merchant
- ranked by `rows_affected × (1.05 - mean_confidence)`: impact times doubt
- merchants that already have verified labels are skipped

One audit answer then fixes a whole group, through three mechanisms:
1. **Sibling flagging** (`set_category`): when a human overturns a model answer, the model's *other identical
   answers* for that merchant are moved to review. A confident mistake is rarely a one-off.
2. The correction becomes a **verified example**, so the next batches see it (§5).
3. Consistent corrections **compile into a rule** that propagates (§5).

Result in the eval: silent errors 7.7% → 0.0% from the second month, for 5 spot-checks a month.

### 4.3 Estimating the error rate you can't see

If you audit `n` *uniformly random* auto-accepted rows and find `e` wrong, the silent-error rate
estimate is `p̂ = e/n`, with a Wilson 95% interval:

```
center = (p̂ + z²/2n) / (1 + z²/n)        half-width = z·sqrt(p̂(1-p̂)/n + z²/4n²) / (1 + z²/n),   z = 1.96
```

With `n = 50` and `e = 1`, `p̂ = 2%` but the interval is roughly [0.4%, 10.5%]. Small audits bound the
error rate only loosely. Note that the impact-weighted sampler above is **biased on purpose** (it hunts
errors). To *estimate* the population rate, use uniform samples, or reweight impact-weighted samples by
the inverse of their selection probability (importance sampling). Use each tool for its job: impact
sampling to *fix* errors, uniform sampling to *measure* them.

---

## 5. Memory: a lifecycle, not a database

Memory is often treated as storage. The hard part is **governance**: what gets written, by whom, how
it's promoted, and how it's forgotten. Ledger Agent's memory types:

| Type (cognitive analogy) | Implementation | Written by | Read by |
|---|---|---|---|
| Working | the prompt of one call / one question | pipeline, agent loop | model |
| Core / pinned (Letta blocks) | `memory_blocks`: household, preferences, goals | user (CLI) and agent (`memory_update`, from what the user *said*) | every categorization batch and every question |
| Semantic facts | `memory_facts` + BM25/recency/importance recall | agent (`remember`) | agent, per question (top-k) |
| Episodic | `labels` (every human decision, with the old model answer); `conversation_turns` | humans only | categorizer (few-shot), rule compiler, agent (history) |
| Procedural (skills) | `rules` (compiled), `import_profiles` | compiled from episodic memory / validated proposals | pipeline, importer, at zero token cost |

### 5.1 Write policy: only verified information

**Nothing the model says is written to memory as truth.** Labels come from humans. Rules compile from
labels. Profiles are saved only after deterministic validation. Facts come from what the user told the agent.

If model outputs were written back as memory ("the model said SWIGGY is Groceries, so remember that"),
the system would **reinforce its own errors**: the next batch sees the wrong example, repeats it with
more confidence, and the error spreads with growing apparent support. This is the agent-scale version
of training on your own outputs. The `labels` table is the barrier: it only accepts human decisions.

### 5.2 Promotion: from episodic to procedural

A single correction is **evidence**. It's used softly, as a retrieved few-shot example (dynamic
few-shot = retrieval over episodic memory). When the last `N` (default 2) verified labels for a
`(merchant, direction)` agree, the pattern is **compiled** into a deterministic rule (`rules.compile_from_labels`):
- rules run before the model, so that merchant costs 0 tokens from then on
- rules are explicit, inspectable (`ledger rules`) and editable, which a prompt example isn't
- when a rule is compiled it is **propagated** to that merchant's unreviewed and model-labelled rows

This is the harness *ratchet* applied to data. An inferential decision that humans keep making the
same way graduates into a computational control. Over time the system needs less intelligence, not more.

Why `N = 2` and scoping by direction? One correction might be an exception ("this *one* Amazon order
was a gift"). Two agreeing corrections is a cheap, conservative signal. From a Bayesian view, with a
uniform prior on "this merchant is always category C", two agreeing labels give a posterior mean of
(2+1)/(2+2) = 0.75 and three give 0.8. Pick `N` from how costly a wrong rule is compared with a
repeated review. Direction scoping matters because the same counterparty can be both income
(a refund from Amazon) and spending (an Amazon purchase).

### 5.3 Forgetting

Memory that can't be revised becomes confidently wrong over time (*staleness*: the user changes gyms,
the landlord changes). Forgetting is event-driven:
- a correction that contradicts a compiled rule **deactivates** the rule (`invalidate_conflicting`);
  the rule is kept for audit, not deleted
- the next consistent pair of labels compiles the new truth
- facts have `active` and `last_accessed`, and recall is recency-weighted, so unused facts fade in rank

### 5.4 Retrieval for few-shot examples

`retrieve_examples` prefers **same-merchant** verified labels (the most relevant possible evidence),
then fills with the most recent labels (covering general household conventions). Two lessons from
the retrieval literature apply:
- *precision beats volume*: 12 highly relevant examples beat 50 loosely related ones, because every extra
  token competes for attention
- examples go **after** the stable instructions and profile, so the unchanging prefix stays cacheable (§9)

### 5.5 Import profiles are skills

"How to read an HDFC savings export" is procedural knowledge. The first time a new layout appears, a
heuristic or the model *proposes* a profile. A deterministic evaluator (≥ 95% rows parse, and the
running balance reconciles) *accepts or rejects* it, with the error messages fed back for a retry. The
accepted profile is stored under the file's header signature, so every later import of that layout
costs zero tokens. This is Voyager's skill library (P07) with a code verifier, and
evaluator-optimizer (P09) where the evaluator is a program, which is far more reliable than an LLM judge.
When no valid profile is found, the import is **refused**. Guessing with money isn't acceptable.

---

## 6. Correctness engineering for money

These are ordinary backend disciplines, and agent systems need them more because the model adds a
source of nondeterminism:

- **Integer minor units.** `0.1 + 0.2 != 0.3` in floating point. All amounts are paise (`amount_minor INTEGER`),
  parsed through `Decimal`.
- **Idempotent import.** Each row gets a fingerprint `sha256(account | date | amount | normalized
  description | occurrence)`, with a UNIQUE constraint. `occurrence` counts identical rows *within the
  same file*, so two genuine ₹20 chai payments on the same day stay two rows, while re-importing a file
  or importing an overlapping statement inserts nothing twice. (The eval checks this: exactly 6 of 6
  overlapping rows are detected.)
- **Atomic batches and exactly-once effects.** A batch's category writes *and* the run checkpoint
  commit in one SQLite transaction. A crash or a budget stop mid-batch rolls back the whole batch, so a
  resumed run neither skips nor double-applies work. The run's in-memory stats are rolled back too
  (`snapshot` in `pipeline.py`). LLM calls themselves aren't transactional, so the **content-addressed
  cache** makes re-issuing a rolled-back batch free and deterministic.
- **Degrade, don't die.** An LLM failure on one batch routes that batch to human review and the run
  continues. A budget stop pauses the run with a resumable status.
- **Reconciliation as a sensor.** Banks export the running balance, which is an independent checksum.
  `balance_consistency` verifies `balance[i] = balance[i-1] + amount[i]` in both chronological orders. A
  wrong amount sign or a column swap fails loudly at import time instead of silently corrupting reports.

---

## 7. Prompt injection: threat model and layered defense

**The data plane is attacker-controlled.** Anyone who sends you ₹1 by UPI chooses the narration text
that ends up in your statement and then in the model's context. Treat every description as hostile.

Defenses, in order of strength:

1. **Constrained outputs.** The categorizer can only emit a category enum, a number and a short reason.
   The worst a successful injection can do is *miscategorize*. It can't exfiltrate data or call tools.
2. **Least-privilege tools.** The Q&A agent's only writes are memory notes and *proposals*. It
   can't change categories, delete data or run arbitrary SQL (the authorizer allows SELECT on ledger tables only).
3. **Blast-radius thinking.** Ask, for each model call, what an attacker controlling this input could
   make the output do. The categorizer: a wrong category, caught by audits. The agent: a misleading
   answer, but no state change beyond a queued proposal.
4. **Separation and sanitization.** Data goes in tagged JSON blocks (`<transactions>…`), and markup
   characters and control codes are neutralized (`sanitize_untrusted`). The instructions say explicitly
   that descriptions are data.
5. **Tripwire routing.** `looks_like_injection` doesn't *prevent* injection (regexes can't). It sends
   suspicious rows to a human instead of letting the model decide them. The eval checks that the planted
   injection is always reviewed by a human.

Note the order: the real guarantees come from 1-3, which hold even if the model follows the injected
text. 4-5 lower the odds. Relying only on "tell the model not to follow instructions" is not a defense.

**Privacy** is the other half of the data-plane problem. `redact` masks account numbers, card numbers,
phone numbers, e-mails and person-like UPI handles *before* anything is sent to the provider, while
keeping merchant-like handles (`swiggy@ybl`) because they carry the signal the model needs. Requests
use `store=False`. See [SECURITY.md](SECURITY.md).

---

## 8. Grounding generated numbers

LLMs are unreliable at arithmetic in prose and will cheerfully produce "₹48,200" when the data says
₹42,800. In finance, a fluent wrong number is worse than no number. The report pipeline is split so
each part does what it's good at:

1. **Facts** are computed by SQL (`month_facts`): totals, category shares, month-over-month changes, subscriptions.
2. **Narrative** is written by the model, instructed to use only numbers present in the facts.
3. **Verifier** (`ungrounded_numbers`): extract every number from the narrative, and each must match a
   fact value within ±0.5% (or ±1 unit). Small counts, month numbers and years are allowed.
4. **Retry with feedback**: the offending numbers are sent back to the model. After `max_attempts`,
   sentences with ungrounded numbers are **deleted**, never published.

This is evaluator-optimizer with a *program* as the evaluator. Its limit is that it checks that a
number **exists in the facts**, not that it's **attributed correctly** ("₹32,000 on food" when ₹32,000
was rent passes). The stronger version makes the model emit structured claims
`{metric, category, value}` and verifies each claim against the fact table. That's a good extension exercise.

---

## 9. Context engineering for the Q&A agent

Each question builds a fresh, small context (`agent/loop.py`):

```
instructions = role & rules (static) + today + <memory> pinned blocks + <recalled_facts> (top-5 for this question)
input        = last 6 Q/A pairs of this conversation (text only) + question + this question's tool traffic
```

Choices and their reasons:
- **Only final answers are persisted across turns**, not tool outputs. Tool results are large and stale;
  if the agent needs them again, it re-queries (cheap, and fresh).
- **Old tool outputs are cleared within a question** once they pass ~40k chars (P04's cheapest lever),
  keeping the most recent three.
- **Just-in-time retrieval.** The model gets tools that fetch data (`spending_summary`, `run_sql`), not
  the ledger pasted into the prompt. A 5,000-transaction ledger would drown the question.
- **Stateless Responses API.** `store=False` keeps data from being retained for later retrieval, so the
  client owns the conversation. With reasoning models, the reasoning items are returned encrypted
  (`include=["reasoning.encrypted_content"]`) and replayed on the next step, so the model keeps its
  chain of thought across tool calls without the provider storing it.
- **Prompt caching.** Providers cache the *longest unchanged prefix*. Keep static text first, and put
  volatile content (date, recalled facts, the question) later. Ledger Agent puts memory in the
  instructions, which trades some cache hits for simplicity. If your memory blocks change rarely and
  questions are frequent, move them into a stable prefix.
- **Budgets per question** (turns and tokens) turn a runaway loop into a polite "narrow the question".

Tool design (see the P02/P03 lessons): a few high-level tools that match how people ask
(`spending_summary`, `search_transactions`, `recurring_payments`), one general escape hatch (`run_sql`)
made safe by the sandbox, strict schemas with enums, compact human-readable outputs, and actionable
errors ("start_date must be YYYY-MM-DD").

---

## 10. Evaluation methodology

- **Evaluate the system, not the model.** The offline `--fake` eval uses a deliberately mediocre keyword
  model. It tests *the harness*: learning, routing, safety, idempotency, grounding. It's deterministic,
  so it can gate CI. The real eval (`OPENAI_API_KEY`) measures the model inside the harness, and should run on
  a schedule because models and prompts drift.
- **Learning curves over snapshots.** One accuracy number hides what memory is for. The eval reports per
  month: automation, auto-accuracy, *silent-error rate*, human reviews and audits, rule vs model share, tokens.
- **Ablations isolate value.** `--audit 0` shows the audit sampler's contribution (silent errors stay at 7.5%).
  `--no-memory` shows the household block's contribution. Run it against the real model: without it,
  UPI rent to "RAMESH KUMAR" looks like a transfer to a person.
- **pass^k for the agent.** For Q&A, a single correct answer means little. `pass^k` (all `k` trials correct)
  measures the reliability a user experiences.
- **Safety evals are binary gates.** Injection routed to a human, and dedup exact, either pass or the build fails.

---

## Further reading

- Anthropic, *Building effective agents*; *Effective context engineering for AI agents*; *Writing effective tools for agents*; *Demystifying evals for AI agents*
- Martin Fowler, *Harness engineering for coding agent users* (guides/sensors, computational/inferential)
- Geifman & El-Yaniv, *Selective Classification for Deep Neural Networks* (2017): risk-coverage
- Guo et al., *On Calibration of Modern Neural Networks* (2017); Tian et al., *Just Ask for Calibration* (2023): verbalized confidence
- Wang et al., *Self-Consistency Improves Chain of Thought Reasoning* (2022)
- Packer et al., *MemGPT* (2023); Park et al., *Generative Agents* (2023); Chhikara et al., *Mem0* (2025)
- Greshake et al., *Not what you've signed up for: indirect prompt injection* (2023)
- Kleppmann, *Designing Data-Intensive Applications*: idempotence, exactly-once, transactions
