import pytest

from ledger_agent.agent.sql_guard import SQLRejected, run_readonly


def test_select_from_view_works(loaded):
    r = run_readonly(loaded, "SELECT category, SUM(abs_amount) FROM v_transactions GROUP BY category")
    assert r.columns == ["category", "SUM(abs_amount)"] and r.rows


def test_cte_and_functions_allowed(loaded):
    r = run_readonly(loaded, "WITH m AS (SELECT month, amount FROM v_transactions) "
                             "SELECT month, ROUND(SUM(amount), 2) FROM m GROUP BY month")
    assert len(r.rows) == 3


@pytest.mark.parametrize("sql", [
    "DELETE FROM transactions",
    "UPDATE transactions SET category='x'",
    "INSERT INTO rules (pattern_type, pattern, category, source) VALUES ('merchant','A','Other','user')",
    "DROP TABLE transactions",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT * FROM llm_cache",
    "SELECT * FROM memory_blocks",
    "SELECT * FROM sqlite_master",
    "CREATE TABLE t(x)",
])
def test_everything_else_is_denied(loaded, sql):
    with pytest.raises(SQLRejected):
        run_readonly(loaded, sql)
    assert loaded.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 121   # nothing changed


def test_multiple_statements_rejected(loaded):
    with pytest.raises(SQLRejected, match="single"):
        run_readonly(loaded, "SELECT 1 FROM v_transactions; DELETE FROM transactions")


def test_row_limit_and_truncation_note(loaded):
    r = run_readonly(loaded, "SELECT id FROM v_transactions", row_limit=10)
    assert len(r.rows) == 10 and r.truncated and "only the first 10 rows" in r.to_text()


def test_runaway_query_times_out(loaded):
    with pytest.raises(SQLRejected, match="exceeded"):
        run_readonly(loaded, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
                             "SELECT COUNT(*) FROM c, v_transactions", timeout_ms=200)


def test_authorizer_is_removed_afterwards(loaded):
    with pytest.raises(SQLRejected):
        run_readonly(loaded, "DELETE FROM transactions")
    loaded.execute("UPDATE transactions SET merchant = merchant WHERE id = 1")   # normal app writes still work


def test_file_database_uses_separate_readonly_connection(tmp_path, dataset):
    from ledger_agent.db import connect
    from ledger_agent.ingest.importer import import_statement
    from ledger_agent.agent.sql_guard import readonly_connection
    conn = connect(tmp_path / "f.db")
    import_statement(conn, None, "HDFC Savings", "a.csv", dataset.files["hdfc_savings_2026-06.csv"])
    ro = readonly_connection(conn)
    assert ro is not None
    ro.close()
    assert run_readonly(conn, "SELECT COUNT(*) FROM v_transactions").rows[0][0] == 28
    with pytest.raises(SQLRejected):
        run_readonly(conn, "DELETE FROM transactions")
    conn.execute("UPDATE transactions SET merchant = merchant WHERE id = 1")   # main connection untouched
