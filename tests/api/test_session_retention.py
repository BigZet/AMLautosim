import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from scripts.ops.purge_sessions import purge_sessions
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import AsyncSessionLocal


def test_session_retention_is_dry_by_default_bounded_and_repeatable(api, player):
    async def run():
        now = datetime.now(UTC)
        rows = [
            Session(
                user_id=player["id"],
                session_id_hash=uuid4().hex,
                audience="play",
                created_at=now - timedelta(days=30),
                expires_at=now + timedelta(days=expires),
                revoked_at=now + timedelta(days=revoked)
                if revoked is not None
                else None,
            )
            for expires, revoked in [
                (-8, None),
                (1, -8),
                (-1, None),
                (1, -1),
                (1, None),
            ]
        ]
        async with AsyncSessionLocal() as db:
            db.add_all(rows)
            await db.commit()
        ids = [r.id for r in rows]

        async def stored():
            async with AsyncSessionLocal() as db:
                return set(
                    (
                        await db.execute(select(Session.id).where(Session.id.in_(ids)))
                    ).scalars()
                )

        result = await purge_sessions(AsyncSessionLocal, now=now)
        assert result == {"eligible": 2, "deleted": 0, "dry_run": True}
        assert await stored() == set(ids)
        result = await purge_sessions(
            AsyncSessionLocal, now=now, apply=True, batch_size=1, max_batches=1
        )
        assert result["deleted"] == 1
        assert len(await stored()) == 4
        result = await purge_sessions(
            AsyncSessionLocal, now=now, apply=True, batch_size=1
        )
        assert result["deleted"] == 1
        assert await stored() == set(ids[2:])
        assert (await purge_sessions(AsyncSessionLocal, now=now, apply=True))[
            "deleted"
        ] == 0
        async with AsyncSessionLocal() as db:
            assert await db.get(User, player["id"]) is not None

    asyncio.run(run())
