# Operations

## Deploy

**Local (single user):** `pip install -e .`, build the UI once (`cd ui && npm ci && npm run build`), set
`OPENAI_API_KEY`, then `ledger serve` and open http://127.0.0.1:8000 (or use the `ledger …` CLI). Data lives in
`data/ledger.db` (`LEDGER_DB_PATH`). Without a built UI, `ledger serve` still serves the full API.

**Upgrading the UI** is part of the Python release: CI builds `ui/` into `src/ledger_agent/static`, which the
wheel and the Docker image include. Hashed assets are cached for a year; `index.html` is served `no-cache`, so a
deploy takes effect on the next page load.

**Docker:**
```bash
docker build -t ledger-agent .
docker run -d --name ledger -p 8000:8000 -v ledger-data:/data \
  -e OPENAI_API_KEY=sk-... -e LEDGER_API_KEY=$(openssl rand -hex 24) ledger-agent
curl -H "Authorization: Bearer $LEDGER_API_KEY" localhost:8000/v1/stats
```
The image (three stages: Node builds the UI, Python builds a wheel containing it, a slim runtime) runs as a
non-root user, serves the web app and the API on :8000, logs JSON to stderr, keeps state in the `/data`
volume, and has a `/healthz` healthcheck. Put a TLS-terminating reverse proxy in front if it's reachable from anywhere but localhost.

## Configuration reference

All settings are in `src/ledger_agent/config.py` (env prefix `LEDGER_`). The ones you'll tune:

| Setting | Default | Tune when |
|---|---|---|
| `MODEL_BULK` / `MODEL_AGENT` | gpt-5.4-mini / gpt-5.4 | re-run the eval after any change |
| `REASONING_EFFORT_BULK` / `_AGENT` | low / medium | raise if accuracy is short; lower for cost |
| `AUTO_ACCEPT_CONFIDENCE` | 0.80 | review load vs silent errors (THEORY §3) |
| `BATCH_SIZE` | 20 | accuracy vs tokens per transaction (THEORY §2.2) |
| `FEW_SHOT_EXAMPLES` | 12 | more labels → more useful examples |
| `RULE_MIN_CONSISTENT_CORRECTIONS` | 2 | raise if compiled rules are wrong too often |
| `MAX_TOKENS_PER_RUN` | 400k | hard stop for one processing run |
| `AGENT_MAX_TURNS` / `AGENT_MAX_TOKENS_PER_QUESTION` | 12 / 120k | runaway protection for Q&A |
| `PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` | unset | set from the provider's price page to get $ in `llm_calls.cost_usd` |
| `LLM_CACHE` | true | turn off only when debugging prompt changes |
| `REDACT_PII` | true | never turn off in production |

## Monitoring

`ledger stats` / `GET /v1/stats` reports the key indicators:

| Signal | Healthy | Investigate when |
|---|---|---|
| `automation_rate` | rising month over month | flat or falling: rules not compiling? new bank? threshold too high? |
| `review_backlog` | small, drained weekly | growing: users aren't reviewing, so stale data goes into reports |
| `llm[*].errors` | ~0 | >1%: provider incidents, bad model name, schema problems |
| `llm[*].hits` (cache hits) | >0 on re-runs | 0 while re-running: prompt or schema changed (expected) or the cache is off |
| runs with `paused_budget` | rare | frequent: raise the budget or process in smaller `--limit` chunks |

Useful SQL (`sqlite3 data/ledger.db`):
```sql
-- tokens & cost per day and purpose
SELECT date(created_at) d, purpose, SUM(input_tokens+output_tokens) tok, ROUND(SUM(cost_usd),4) usd
FROM llm_calls GROUP BY d, purpose ORDER BY d DESC;
-- why things go to review
SELECT review_reason, COUNT(*) FROM transactions WHERE status='needs_review' GROUP BY 1;
-- rules doing the most work (and ones that never fire)
SELECT id, pattern, category, source, hits FROM rules WHERE active=1 ORDER BY hits DESC;
-- how often humans overturn the model, by category (a drift signal)
SELECT old_category, category, COUNT(*) FROM labels WHERE kind='correction' GROUP BY 1,2 ORDER BY 3 DESC;
```

Logs: every line has `run_id` (`chat-<conversation>` for Q&A), so one grep reconstructs a run. With
`LEDGER_LOG_FORMAT=json` the logs are ready for any log pipeline.

## Runbooks

**A run shows `paused_budget`.** Nothing was half-applied, because the in-flight batch rolled back.
Resume with `ledger process --resume <run_id>` (or `POST /v1/process?resume=<id>`), after raising
`LEDGER_MAX_TOKENS_PER_RUN` if the pause was unexpected.

**Provider outage / many `llm_errors`.** Batches degrade to `needs_review` with reason `llm_no_answer`,
and imports of known formats keep working (profiles are cached). After recovery, requeue those rows:
```sql
UPDATE transactions SET status='pending', review_reason=NULL WHERE review_reason='llm_no_answer';
```
then run `ledger process`.

**A compiled rule is wrong.** Correct one affected transaction in `ledger review`. The contradiction
deactivates the rule automatically. To kill it immediately: `UPDATE rules SET active=0 WHERE id=?`.

**A bank changed its export format.** The stored profile fails validation, and `resolve_profile` logs
`stored profile failed validation; re-learning` and learns a new one. If the import is refused, check the
error: it names the rows and the reason (usually a new date format or amount column).

**Imported into the wrong account.** Delete that import's rows in one transaction:
```sql
BEGIN; DELETE FROM labels WHERE transaction_id IN (SELECT id FROM transactions WHERE import_id=?);
DELETE FROM transactions WHERE import_id=?; DELETE FROM imports WHERE id=?; COMMIT;
```

**Backups.** SQLite online backup (safe while running): `sqlite3 data/ledger.db ".backup data/backup-$(date +%F).db"`.
Restore by stopping the app and replacing the file. Test restores.

**Schema migrations.** Append a new SQL string to `db.MIGRATIONS`. It runs once, atomically, at the next
start. Never edit a released migration.

## Cost control, in order of impact

1. **Rules and memory**: every compiled rule removes model calls for a merchant permanently. Review and audit regularly.
2. **Cache**: identical re-runs are free.
3. **Model choice and effort**: bulk work on the small model at low effort; measure before upgrading.
4. **Batch size**: larger batches amortize the fixed prompt (watch accuracy in the eval).
5. **Budgets**: per run and per question, so a bug can never mean an unbounded bill.

## Scaling path

This is a single-user system by design. To serve many users:
1. **Postgres**: port `db.py` (SQL is standard apart from `INSERT OR IGNORE`/`RETURNING`, which become `ON CONFLICT DO NOTHING`/`RETURNING`), add `user_id` to every table, use row-level security.
2. **Background workers**: `POST /v1/process` enqueues a job (Redis/RQ, Celery, or a DB-backed queue); workers run `process_pending`. The checkpoint design already makes jobs safely retryable.
3. **Batch API**: non-interactive categorization can use the provider's batch endpoint (much cheaper, higher latency).
4. **Per-user budgets and rate limits** in the service layer; per-tenant cache keys.
5. **Shared, opt-in merchant knowledge** ("ZOMATO is Food:Delivery for 99% of users") as a global rule tier *below* each user's own rules. It needs privacy review first.
