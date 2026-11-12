"""Seed a database with the demo statements, categorised by the OFFLINE keyword model (no API key).

    python scripts/seed_demo_db.py data/demo.db
    LEDGER_DB_PATH=data/demo.db ledger serve        # then open http://127.0.0.1:8000

For UI development and screenshots: realistic volume, a review queue, an audit sample, learned rules,
and household memory, all without spending tokens. Never point it at your real ledger.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledger_agent.categorize.pipeline import process_pending  # noqa: E402
from ledger_agent.categorize.review import review_queue, set_category  # noqa: E402
from ledger_agent.config import Settings  # noqa: E402
from ledger_agent.datagen import HOUSEHOLD_MEMORY, generate  # noqa: E402
from ledger_agent.db import connect  # noqa: E402
from ledger_agent.ingest.importer import import_statement  # noqa: E402
from ledger_agent.llm.fake import FakeLLM, keyword_parse_handler  # noqa: E402
from ledger_agent.memory import ensure_blocks, remember, update_block  # noqa: E402


def main(path: str) -> None:
    db = Path(path)
    if db.exists():
        raise SystemExit(f"{db} already exists - refusing to touch an existing ledger.")
    settings = Settings(db_path=db, _env_file=None)
    conn = connect(db)
    ensure_blocks(conn)
    update_block(conn, "household", "", HOUSEHOLD_MEMORY)
    update_block(conn, "goals", "", "Keep food delivery under ₹3,000 a month. Save ₹40,000 a month towards a Japan trip.")
    remember(conn, "User is saving for a trip to Japan in December 2026", 7)
    ds = generate(seed=7)
    truth = {(t.day.isoformat(), t.amount_minor, t.description): t.category for t in ds.labels}
    llm = FakeLLM(parse_handler=keyword_parse_handler)
    for i, month in enumerate(ds.months):
        for account, fname in ds.files_by_month[month]:
            import_statement(conn, None, account, fname, ds.files[fname])
        last = i == len(ds.months) - 1
        # the latest month is processed with a stricter bar, so its uncertain entries wait in Review
        run_settings = settings.model_copy(update={"auto_accept_confidence": 0.86}) if last else settings
        process_pending(conn, llm, run_settings)
        if not last:          # a person worked through earlier months; the latest waits for you
            for item in review_queue(conn, 1000):
                t = conn.execute("SELECT date, amount_minor, description, status FROM transactions WHERE id=?",
                                 (item["id"],)).fetchone()
                if t["status"] == "needs_review":
                    set_category(conn, item["id"], truth[(t["date"], t["amount_minor"], t["description"])])
    print(f"seeded {db}: {conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]} transactions")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/demo.db")
