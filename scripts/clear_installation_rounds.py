"""Explicit, transactional one-time cleanup after a verified local pg_dump backup."""

import argparse
import asyncio
from pathlib import Path
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.db.session import AsyncSessionLocal, async_engine
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent


async def clear(database, backup):
    actual = make_url(settings.database_url).database
    if actual != database:
        raise ValueError("Target database does not match explicit installation name")
    if not backup.is_file() or backup.stat().st_size < 1024:
        raise ValueError("A nonempty pg_dump custom-format backup is required")
    with backup.open('rb') as stream:
        if stream.read(5) != b'PGDMP':
            raise ValueError('A pg_dump custom-format backup is required')
    try:
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(text("SELECT pg_advisory_xact_lock(73419001)"))
            ids = list((await db.scalars(select(Round.id).with_for_update())).all())
            await db.execute(delete(AuditEvent).where(AuditEvent.round_id.in_(ids)))
            await db.execute(
                delete(ScoringResult).where(
                    ScoringResult.scenario_id.in_(
                        select(Scenario.id).where(Scenario.round_id.in_(ids))
                    )
                )
            )
            await db.execute(delete(Scenario).where(Scenario.round_id.in_(ids)))
            await db.execute(delete(Round).where(Round.id.in_(ids)))
        print(
            {"database": actual, "removed_rounds": ids, "backup": str(backup.resolve())}
        )
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", required=True)
    p.add_argument("--backup", required=True, type=Path)
    args = p.parse_args()
    asyncio.run(clear(args.database, args.backup))
