from __future__ import annotations

import pytest

from lakehouse.sql_catalog import SqlStatement, load_catalog, split_statements

SQL = """
-- header comment
CREATE TABLE x (a int);

-- @query: by_days
-- @title: Example
-- @question: How many?
--   continued question line
-- @params: days=7, agent='qa-assistant'
SELECT ':not_a_param', a FROM x
WHERE d >= current_date - (:days * INTERVAL '1' DAY) AND agent = :agent AND note = 'it''s; fine';
"""


def test_split_respects_strings_and_comments():
    parts = split_statements(SQL)
    assert len(parts) == 2
    assert parts[1][1].endswith("'it''s; fine'")


def test_tags_and_binding():
    comments, body = split_statements(SQL)[1]
    from lakehouse.sql_catalog import load_file  # noqa: F401  (exercise via SqlStatement directly)
    st = SqlStatement(file="t.sql", index=1, sql=body,
                      tags={"query": "by_days", "params": "days=7, agent='qa-assistant'"})
    sql, params = st.bind({"days": 30})
    assert params == [30, "qa-assistant"]
    assert "':not_a_param'" in sql  # untouched inside literal
    assert sql.count("?") == 2
    with pytest.raises(ValueError):
        st.bind({"evil": "1; DROP TABLE x"})


def test_repository_sql_catalog_is_well_formed():
    catalog = load_catalog()
    for name, st in catalog.items():
        for tag in ("title", "concept", "question"):
            assert st.tags.get(tag), f"{name} missing @{tag}"
        sql, params = st.bind()
        assert sql.count("?") == len(params), name
