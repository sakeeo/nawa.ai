import pytest

from nawa.data.guard import ALLOWED_FUNCTIONS, FORBIDDEN_FUNCTIONS, GuardResult, check_sql

ALLOW: dict[str, set[str]] = {
    "outlets": {"id", "name", "city"},
    "orders": {"id", "outlet_id", "customer_id", "channel", "amount", "created_at"},
    "customers": {"id", "outlet_id"},  # customers.name is omitted: personal data
    "order_items": {"id", "order_id", "menu_item_id", "quantity", "unit_price"},
    "menu_items": {"id", "name", "category", "food_cost", "price"},
}

ACCEPTED = [
    "SELECT COUNT(*) FROM orders",
    "SELECT name FROM outlets",
    "SELECT outlets.name, SUM(order_items.quantity * order_items.unit_price) AS revenue"
    " FROM orders JOIN outlets ON orders.outlet_id = outlets.id"
    " JOIN order_items ON order_items.order_id = orders.id"
    " GROUP BY outlets.name ORDER BY revenue DESC",
    "WITH monthly AS (SELECT DATE_TRUNC('month', created_at) AS month, COUNT(*) AS n"
    " FROM orders GROUP BY 1) SELECT month, n FROM monthly ORDER BY month",
    "SELECT id FROM orders UNION SELECT id FROM outlets",
    "SELECT id, ROW_NUMBER() OVER (PARTITION BY outlet_id ORDER BY created_at) AS rn FROM orders",
    "SELECT EXTRACT(year FROM created_at) AS y, ROUND(AVG(COALESCE(amount, 0)), 2) AS avg_amount,"
    " CASE WHEN COUNT(*) > 5 THEN 'many' ELSE 'few' END AS size FROM orders GROUP BY 1",
    "SELECT id FROM public.orders",
    "SELECT channel, COUNT(*) AS n FROM orders GROUP BY channel HAVING COUNT(*) > 1 ORDER BY n",
    "SELECT * FROM orders",
    "SELECT id FROM orders WHERE outlet_id IN (SELECT id FROM outlets WHERE city = 'Bandung')",
    "SELECT SUM(amount) / NULLIF(COUNT(*), 0) AS aov, MAX(created_at)::date AS last_day FROM orders"
    " WHERE created_at >= DATE '2025-08-01' AND created_at < DATE '2025-09-01'",
    "SELECT 1;",
    "SELECT TO_CHAR(created_at, 'YYYY-MM') AS ym, COUNT(*) FROM orders GROUP BY 1",
    "SELECT o.id FROM orders o JOIN outlets AS t ON o.outlet_id = t.id",
    "SELECT name FROM outlets WHERE name ILIKE '%jak%' AND city IS NOT NULL",
]

FORBIDDEN = [
    "DROP TABLE orders",
    "UPDATE orders SET amount = 0",
    "DELETE FROM orders",
    "INSERT INTO orders (id) VALUES (1)",
    "TRUNCATE orders",
    "COPY orders TO '/tmp/x'",
    "CREATE TABLE x (a int)",
    "GRANT ALL ON orders TO public",
    "SELECT 1; SELECT 2",
    "SELECT id FROM orders; DROP TABLE orders",
    "/* ; */ DROP TABLE orders",
    "SELECT * INTO t FROM orders",
    "SELECT id FROM orders FOR UPDATE",
    "EXPLAIN SELECT 1",
    "SET statement_timeout = 0",
    "VALUES (1)",
    "SELECT pg_sleep(10)",
    "select PG_SLEEP(1)",
    "SELECT pg_catalog.pg_sleep(1)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT public.pg_read_file('x')",
    "SELECT current_setting('server_version')",
    "SELECT set_config('a', 'b', false)",
    "SELECT dblink('x', 'select 1')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT query_to_xml('select * from customers', true, true, '')",
    "SELECT * FROM pg_shadow",
    "SeLeCt * FrOm PG_SHADOW",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM public.secrets",
    "SELECT * FROM secrets",
    'SELECT * FROM "Orders"',
    "SELECT * FROM other_db.public.orders",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    "WITH secrets AS (SELECT * FROM secrets) SELECT * FROM secrets",
    "WITH orders AS (SELECT * FROM secrets) SELECT * FROM orders",
    "SELECT * FROM customers AS c(a, b, d)",
    "SELECT customers FROM customers",
    "SELECT c FROM customers c",
    "SELECT c::text FROM customers c",
    "SELECT row_to_json(c) FROM customers c",
    "SELECT public.sum(amount) FROM orders",
    "SELECT pg_catalog.count(*) FROM orders",
    'SELECT "public"."sum"(amount) FROM orders',
]

REPAIRABLE = [
    "",
    "SELEC 1",
    "SELECT FROM WHERE",
    "SELECT * FROM orders WHERE",
    "SELECT nope FROM orders",
    "SELECT name FROM customers",
    "SELECT c.name FROM customers c",
    "SELECT customers.name FROM customers",
    "SELECT foo_bar(id) FROM orders",
    "SELECT unnest(ARRAY[1, 2])",
    "SELECT * FROM orders FETCH FIRST 5 ROWS ONLY",
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepts_read_only_queries_and_adds_a_limit(sql: str) -> None:
    result = check_sql(sql, ALLOW)
    assert result.ok, result.reason
    assert result.kind == "ok" and result.reason is None and result.sql
    assert result.sql.upper().rstrip().endswith("LIMIT 1000")


@pytest.mark.parametrize("sql", ACCEPTED)
def test_checking_the_output_again_changes_nothing(sql: str) -> None:
    first = check_sql(sql, ALLOW)
    assert first.sql is not None
    second = check_sql(first.sql, ALLOW)
    assert second.ok and second.sql == first.sql


@pytest.mark.parametrize("sql", FORBIDDEN)
def test_forbidden_statements_are_final(sql: str) -> None:
    result = check_sql(sql, ALLOW)
    assert not result.ok
    assert result.kind == "forbidden", (sql, result.reason)
    assert result.sql is None and result.reason
    assert result.tables == frozenset() or result.tables <= set(ALLOW)


@pytest.mark.parametrize("sql", REPAIRABLE)
def test_fixable_mistakes_are_repairable(sql: str) -> None:
    result = check_sql(sql, ALLOW)
    assert not result.ok
    assert result.kind == "repairable", (sql, result.kind, result.reason)
    assert result.sql is None and result.reason


def test_reasons_never_echo_literals_from_the_query() -> None:
    result = check_sql("SELECT pg_read_file('/etc/passwd')", ALLOW)
    assert result.reason and "/etc/passwd" not in result.reason


def test_star_expands_only_to_allowed_columns() -> None:
    result = check_sql("SELECT * FROM customers", ALLOW)
    assert result.ok and result.sql
    lowered = result.sql.lower()
    assert "name" not in lowered
    assert "id" in lowered and "outlet_id" in lowered
    qualified = check_sql("SELECT c.* FROM customers c", ALLOW)
    assert qualified.ok and qualified.sql and "name" not in qualified.sql.lower()


def test_omitted_column_cannot_be_reached_through_a_subquery_or_cte() -> None:
    for sql in (
        "SELECT x.name FROM (SELECT * FROM customers) x",
        "WITH c AS (SELECT * FROM customers) SELECT name FROM c",
    ):
        assert check_sql(sql, ALLOW).kind == "repairable", sql


def test_comments_are_stripped_not_executed() -> None:
    result = check_sql("SELECT 1 -- ; DROP TABLE x", ALLOW)
    assert result.ok and result.sql
    assert "DROP" not in result.sql.upper() and "--" not in result.sql
    block = check_sql("SELECT id FROM orders /* ; DROP TABLE orders */", ALLOW)
    assert block.ok and block.sql and "DROP" not in block.sql.upper()


def test_tables_lists_only_real_tables_not_ctes() -> None:
    result = check_sql(
        "WITH a AS (SELECT outlet_id FROM orders) SELECT outlets.name FROM a"
        " JOIN outlets ON a.outlet_id = outlets.id",
        ALLOW,
    )
    assert result.ok
    assert result.tables == frozenset({"orders", "outlets"})


def test_limit_is_added_clamped_or_kept() -> None:
    def limit_of(sql: str, **kwargs: int) -> str:
        result = check_sql(sql, ALLOW, **kwargs)
        assert result.ok and result.sql, result.reason
        return result.sql.upper()

    assert limit_of("SELECT id FROM orders").endswith("LIMIT 1000")
    assert limit_of("SELECT id FROM orders LIMIT 5000").endswith("LIMIT 1000")
    assert limit_of("SELECT id FROM orders LIMIT 10").endswith("LIMIT 10")
    assert limit_of("SELECT id FROM orders LIMIT ALL").endswith("LIMIT 1000")
    assert limit_of("SELECT id FROM orders", max_rows=50).endswith("LIMIT 50")
    assert limit_of("SELECT id FROM orders LIMIT 900", max_rows=50).endswith("LIMIT 50")
    with_offset = limit_of("SELECT id FROM orders LIMIT 10 OFFSET 20")
    assert "LIMIT 10" in with_offset and "OFFSET 20" in with_offset


def test_inner_limit_does_not_count_as_the_outer_limit() -> None:
    result = check_sql("SELECT id FROM (SELECT id FROM orders LIMIT 5) t", ALLOW)
    assert result.ok and result.sql
    assert result.sql.upper().count("LIMIT") == 2
    assert result.sql.upper().rstrip().endswith("LIMIT 1000")


def test_union_gets_an_outer_limit() -> None:
    result = check_sql("SELECT id FROM orders UNION ALL SELECT id FROM outlets", ALLOW)
    assert result.ok and result.sql and result.sql.upper().rstrip().endswith("LIMIT 1000")


def test_function_lists_do_not_overlap_and_cover_the_basics() -> None:
    assert not ALLOWED_FUNCTIONS & FORBIDDEN_FUNCTIONS
    assert {"SUM", "COUNT", "AVG", "DATE_TRUNC", "COALESCE", "ROUND"} <= ALLOWED_FUNCTIONS
    assert {"pg_sleep", "pg_read_file", "dblink", "set_config", "current_setting"} <= {
        name.lower() for name in FORBIDDEN_FUNCTIONS
    }
    assert not any(name.lower().startswith(("pg_", "lo_")) for name in ALLOWED_FUNCTIONS)


def test_result_type_is_immutable() -> None:
    result = check_sql("SELECT 1", ALLOW)
    assert isinstance(result, GuardResult)
    with pytest.raises(AttributeError):
        result.ok = False  # type: ignore[misc]


def test_empty_allowlist_denies_every_table() -> None:
    assert check_sql("SELECT id FROM orders", {}).kind == "forbidden"
    assert check_sql("SELECT 1", {}).ok
