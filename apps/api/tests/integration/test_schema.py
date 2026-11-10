import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

import nawa.core.audit  # noqa: F401  (registers AuditLog)
import nawa.knowledge.models  # noqa: F401  (registers knowledge models)
import nawa.workspace.models  # noqa: F401  (registers workspace models)
from nawa.core.db import Base

APP_ROLE = "nawa_app_test"


async def test_every_model_column_exists_in_the_migrated_database(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table.name},
            )
            assert {r[0] for r in rows} == {c.name for c in table.columns}, table.name


async def test_app_role_is_not_superuser_and_cannot_bypass_rls(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"),
                {"r": APP_ROLE},
            )
        ).one()
    assert (row[0], row[1]) == (False, False)


async def test_app_role_owns_no_tables(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        owners = (
            (
                await conn.execute(
                    text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
                )
            )
            .scalars()
            .all()
        )
    assert APP_ROLE not in owners


async def test_audit_logs_are_append_only_for_the_app_role(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("DELETE FROM audit_logs"))


async def test_instance_settings_row_exists(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT setup_completed FROM instance_settings WHERE id = 1"))
        ).one()
    assert row[0] is False
