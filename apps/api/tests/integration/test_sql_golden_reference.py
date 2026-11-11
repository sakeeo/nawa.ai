from pathlib import Path

from nawa.data.connector import ConnectionParams
from nawa.data.executor import execute_readonly
from nawa.data.guard import check_sql, mark_checked
from nawa.data.semantic import allowlist, parse_semantic_yaml
from nawa.evaluation.sql_dataset import SqlItem, load_sql_golden

ROOT = Path(__file__).resolve().parents[4]
GOLDEN = ROOT / "evals" / "sql_golden.yaml"
ALLOW = allowlist(parse_semantic_yaml((ROOT / "seed" / "noesantara_semantic.yaml").read_text()))


async def _run(params: ConnectionParams, item: SqlItem):  # type: ignore[no-untyped-def]
    verdict = check_sql(item.reference_sql, ALLOW)
    assert verdict.ok, (item.id, verdict.reason)
    return await execute_readonly(params, mark_checked(verdict), timeout_s=30, max_rows=1000)


async def test_every_reference_sql_runs_and_answers(demo_database: object) -> None:
    assert isinstance(demo_database, ConnectionParams)
    items, _ = load_sql_golden(GOLDEN, allow=ALLOW)
    for item in items:
        result = await _run(demo_database, item)
        assert result.row_count >= 1 or "empty_ok" in item.tags, item.id
        assert not result.truncated, item.id
        if item.ordered and "top1" in item.tags:
            assert result.row_count == 1, item.id


async def test_reference_answers_match_the_hand_checked_facts_of_the_seed(
    demo_database: object,
) -> None:
    assert isinstance(demo_database, ConnectionParams)
    items = {i.id: i for i in load_sql_golden(GOLDEN, allow=ALLOW)[0]}

    async def rows(item_id: str) -> list[list[object]]:
        return (await _run(demo_database, items[item_id])).rows

    # If the seed generator ever changes, these fail and the whole dataset must be re-checked.
    assert await rows("E01") == [[5]]
    assert await rows("E03") == [[72]]
    assert await rows("E07") == [[59193]]
    assert await rows("E09") == [[500]]
    assert await rows("E11") == [[16]]
    assert await rows("E18") == [[6]]
    assert await rows("E16") == [[15013847000]]
    assert await rows("M03") == [[1309223000]]  # "bulan ini" is December 2025
    assert await rows("M04") == [[1240691000]]  # "bulan lalu" is November 2025
    # The planted anomaly: no beef reaches Bandung in August 2025.
    assert await rows("M16") == [[0]]
    assert await rows("M15") == [["Daging Sapi", "Bandung"]]
    assert await rows("H01") == [["Bandung"]]
    assert await rows("H07") == [[0]]
    assert await rows("H08") == [["Bandung", 180613000]]
    # Cut-off ties were checked: the four cheapest menus are unambiguous.
    assert [r[1] for r in await rows("E15")] == [12000, 14000, 15000, 15000]
    assert await rows("H04") == [["Yogyakarta"]]
