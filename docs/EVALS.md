# Evals

```bash
python evals/run_evals.py --fake                                  # offline, deterministic, ~2 s
python evals/run_evals.py --fake --check evals/baseline_fake.json # CI gate (exit 1 on regression)
python evals/run_evals.py                                         # real OpenAI models (+ Q&A, pass^k)
python evals/run_evals.py --audit 0        # ablation: no audit sampling
python evals/run_evals.py --no-memory      # ablation: no household memory block
python evals/run_evals.py --trials 5       # Q&A trials per task (pass^5)
```

Each run writes `evals/results/<timestamp>-<mode>.json` with every metric plus examples of silent
errors and Q&A answers. **Read those files**: a metric tells you *that* something changed, and only
the examples tell you *why*.

## The dataset

`ledger_agent/datagen.py` generates 3 months × 2 accounts (121 transactions) with ground-truth labels.
It's built to exercise specific behaviours:

| Trap | Exercises |
|---|---|
| UPI rent to a person (RAMESH KUMAR) | household memory |
| a cafe and a clothing store the baseline doesn't know | learning from corrections |
| "THIRD WAVE COFFEE" (contains FEE) | silent errors → audit sampling |
| Netflix ₹649 → ₹799 in month 3 | recurring detection, price change |
| each savings statement repeats the previous one's last 3 rows | dedup (exactly 6 duplicates expected) |
| ₹1 credit with an injection narration | tripwire → human, never auto |
| card bill payment / "PAYMENT RECEIVED" | Transfers:Self across accounts |
| split vs Dr/Cr CSV formats, preamble, footer | import profiles, header detection |

## Metrics

| Metric | Definition | Why it matters |
|---|---|---|
| automation rate | categorized without a human / new transactions | the user's workload |
| auto accuracy | correct / auto-categorized | quality of what users *don't* look at |
| **silent error rate** | auto-categorized **and** wrong / all new | the harm metric: errors nobody sees |
| human reviews + audits | queue items answered + spot-checks | human cost of the learning loop |
| rule / llm | auto-categorized by each tier | cost structure; rules are free |
| tokens, llm_calls | from the usage meter | cost per month |
| injection_routed_to_human | the injected row ended as a human decision | safety gate |
| dedup_exact | duplicates detected == expected | idempotency gate |
| grounded | no unverified number published in the report | grounding gate |
| Q&A pass@1, pass^k | per task, k trials; answer contains the right number (±1%) | agent reliability |

## Reading results

Baseline measured with the offline keyword model:

| month | automation | auto accuracy | silent errors | reviews + audits | rule/llm |
|---|---:|---:|---:|---:|---:|
| 2026-06 | 77% | 90% | 7.7% | 10 + 5 | 0/30 |
| 2026-07 | 98% | 100% | 0.0% | 1 + 5 | 4/37 |
| 2026-08 | 100% | 100% | 0.0% | 0 + 5 | 6/34 |

With `--audit 0`, silent errors stay at ~7.5% every month and reviews look "better" (0 + 0).
That's the trap: a system can look increasingly automated while quietly being wrong. Always report
silent errors next to automation.

## Adding tasks

- **New trap**: add rows to `_savings_month` / `_card_month` with the true category, then a check in `run_evals.py`.
- **New Q&A task**: append `(question, truth_fn(labels))` to `QA`. Compute truth from *labels*, not from
  the DB, so categorization errors show up as Q&A failures (end-to-end).
- **New gate**: add a threshold to `baseline_fake.json` and a condition in `check()`. Set thresholds
  slightly below measured values, and tighten them as the system improves (the ratchet, for evals).

## Offline vs real evals

- The **offline** eval tests the **harness** (routing, learning, idempotency, safety, grounding) with a
  deliberately mediocre deterministic model. It gates every commit.
- The **real** eval tests the **model in the harness**. Run it before changing prompts, models, effort or
  thresholds, and on a schedule (models drift). Compare runs with the JSON files. When a change helps
  one metric and hurts another, the silent-error rate usually decides.
