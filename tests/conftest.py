import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledger_agent.config import Settings  # noqa: E402
from ledger_agent.datagen import generate  # noqa: E402
from ledger_agent.db import connect  # noqa: E402
from ledger_agent.ingest.importer import import_statement  # noqa: E402
from ledger_agent.llm.fake import FakeLLM, keyword_parse_handler  # noqa: E402
from ledger_agent.memory import ensure_blocks  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "test.db", _env_file=None)


@pytest.fixture
def conn():
    c = connect(":memory:")
    ensure_blocks(c)
    yield c
    c.close()


@pytest.fixture(scope="session")
def dataset():
    return generate(seed=7)


@pytest.fixture
def keyword_llm():
    return FakeLLM(parse_handler=keyword_parse_handler)


@pytest.fixture
def loaded(conn, dataset):
    """A DB with all three months of both accounts imported (not yet categorized)."""
    for m in dataset.months:
        for account, fname in dataset.files_by_month[m]:
            import_statement(conn, None, account, fname, dataset.files[fname])
    return conn


def truth_by_key(dataset):
    return {(t.day.isoformat(), t.amount_minor, t.description): t.category for t in dataset.labels}
