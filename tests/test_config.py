from ledger_agent.config import Settings
from ledger_agent.service import LedgerService


def test_api_key_is_read_from_env_file(tmp_path, monkeypatch, conn):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-file\nLEDGER_BATCH_SIZE=7\n", encoding="utf-8")
    s = Settings(db_path=tmp_path / "x.db", _env_file=env)
    assert s.openai_api_key.get_secret_value() == "sk-from-file" and s.batch_size == 7
    assert "sk-from-file" not in repr(s)                          # never printed in logs or tracebacks
    svc = LedgerService(s, conn=conn)
    assert svc.llm is not None and svc.llm.client.api_key == "sk-from-file"


def test_environment_wins_over_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-file\n", encoding="utf-8")
    assert Settings(_env_file=env).openai_api_key.get_secret_value() == "sk-from-env"


def test_no_key_means_no_model(tmp_path, monkeypatch, conn):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert LedgerService(Settings(db_path=tmp_path / "x.db", _env_file=None), conn=conn).llm is None
