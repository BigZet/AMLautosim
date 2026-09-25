"""Dry-run by default; purge old expired/revoked sessions in bounded batches."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import delete, func, or_, select

from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.session import AsyncSessionLocal


async def purge_sessions(
    sessions, *, now=None, retention_days=7, apply=False, batch_size=500, max_batches=20
):
    if (
        retention_days < 1
        or not 1 <= batch_size <= 1000
        or not 1 <= max_batches <= 1000
    ):
        raise ValueError("invalid_retention_bounds")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    eligible = or_(Session.expires_at <= cutoff, Session.revoked_at <= cutoff)
    async with sessions() as db:
        count = (
            await db.execute(select(func.count()).select_from(Session).where(eligible))
        ).scalar_one()
        deleted = 0
        if apply:
            for _ in range(max_batches):
                candidates = (
                    select(Session.id)
                    .where(eligible)
                    .order_by(Session.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                result = await db.execute(
                    delete(Session).where(Session.id.in_(candidates))
                )
                deleted += result.rowcount
                await db.commit()
                if result.rowcount < batch_size:
                    break
        return {"eligible": count, "deleted": deleted, "dry_run": not apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(purge_sessions(AsyncSessionLocal, **vars(args)))))


if __name__ == "__main__":
    main()
