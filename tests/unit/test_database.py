"""
Unit tests for TestPulse SQLite database models, WAL mode, and cascade behavior.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from testpulse.models.database import Run, Snapshot, TestPlan


@pytest.mark.asyncio
async def test_sqlite_wal_and_busy_timeout(test_db_session: AsyncSession) -> None:
    """Verifies that WAL mode and busy_timeout=5000 pragmas are active."""
    result = await test_db_session.execute(text("PRAGMA journal_mode"))
    mode = result.scalar()
    # In SQLite, WAL mode on memory/tmp files returns 'wal'
    assert str(mode).lower() == "wal"

    result_timeout = await test_db_session.execute(text("PRAGMA busy_timeout"))
    timeout = result_timeout.scalar()
    assert timeout == 5000


@pytest.mark.asyncio
async def test_create_and_query_run(test_db_session: AsyncSession) -> None:
    """Tests creating a Run record and verifying defaults and timestamps."""
    new_run = Run(
        status="pending",
        workspace_path="/workspace/sample_app",
        config={"test_scope": ["unit"], "max_targets": 5},
    )
    test_db_session.add(new_run)
    await test_db_session.commit()
    await test_db_session.refresh(new_run)

    assert new_run.id is not None
    assert new_run.status == "pending"
    assert new_run.config["max_targets"] == 5
    assert new_run.created_at is not None


@pytest.mark.asyncio
async def test_run_cascade_deletion(test_db_session: AsyncSession) -> None:
    """Tests that deleting a Run cascades and removes associated snapshots and test plans."""
    run = Run(
        status="analyzing",
        workspace_path="/workspace/sample_app",
        config={"test_scope": ["unit"]},
    )
    test_db_session.add(run)
    await test_db_session.flush()

    snapshot = Snapshot(
        run_id=run.id,
        snapshot_label="T0",
        graph_json_path="/testpulse/snapshots/t0.json",
        ast_hashes={"app.py": "abc123hash"},
    )
    test_db_session.add(snapshot)
    await test_db_session.flush()

    plan = TestPlan(
        run_id=run.id,
        snapshot_id=snapshot.id,
        strategy="unit",
        target_symbol="create_order",
        target_file="app/services/orders.py",
        behavior_matrix=[{"behavior_id": "B01", "name": "happy_path"}],
    )
    test_db_session.add(plan)
    await test_db_session.commit()

    # Verify records exist
    res = await test_db_session.get(Snapshot, snapshot.id)
    assert res is not None

    # Delete the parent run
    await test_db_session.delete(run)
    await test_db_session.commit()

    # Verify child records were cascaded
    deleted_snapshot = await test_db_session.get(Snapshot, snapshot.id)
    assert deleted_snapshot is None
    deleted_plan = await test_db_session.get(TestPlan, plan.id)
    assert deleted_plan is None
