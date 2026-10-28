"""Test engine SQL preparation logic (no Exasol needed)."""

from closedesk.engine.run import _prepare_sql, _sanitise_run_id


def test_sanitise_run_id():
    assert _sanitise_run_id("R-2026-10-27-abc123") == "R-2026-10-27-abc123"
    assert _sanitise_run_id("R-2026; DROP TABLE--") == "R-2026DROPTABLE--"


def test_prepare_sql_replaces_bindings():
    raw = """
    -- a comment
    SELECT :run_id, :amount_tol, :time_tol_seconds, :rupees_per_day;
    """
    stmts = _prepare_sql(raw, "R-test", 1.5, 300, 100.0)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert "'R-test'" in stmt
    assert "1.5" in stmt
    assert "300" in stmt
    assert "100.0" in stmt
    assert "--" not in stmt
