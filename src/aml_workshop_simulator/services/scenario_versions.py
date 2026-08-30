"""Append-only draft history.

One helper module so the participant router, the admin router and the scoring
service all read the version history the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.scenario_versions import ScenarioVersion
from src.aml_workshop_simulator.db.models.scenarios import Scenario


async def append_version(
    db: AsyncSession,
    scenario: Scenario,
    *,
    steps: list[dict[str, Any]],
    snapshot: dict[str, Any],
    payload_hash: str,
    created_by_user_id: int,
    label: str | None = None,
    restored_from_revision: int | None = None,
) -> ScenarioVersion:
    """Store the scenario's current chain as a new immutable version."""
    version = ScenarioVersion(
        scenario_id=scenario.id,
        revision=scenario.revision,
        label=label,
        steps=steps,
        resource_snapshot=snapshot,
        payload_hash=payload_hash,
        restored_from_revision=restored_from_revision,
        created_by_user_id=created_by_user_id,
        created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    scenario.current_version_id = version.id
    return version


async def list_versions(
    db: AsyncSession, scenario_id: int
) -> list[ScenarioVersion]:
    return list(
        (
            await db.execute(
                select(ScenarioVersion)
                .where(ScenarioVersion.scenario_id == scenario_id)
                .order_by(ScenarioVersion.revision.desc(), ScenarioVersion.id.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_version(
    db: AsyncSession, scenario_id: int, revision: int
) -> ScenarioVersion | None:
    return (
        await db.execute(
            select(ScenarioVersion).where(
                ScenarioVersion.scenario_id == scenario_id,
                ScenarioVersion.revision == revision,
            )
        )
    ).scalars().first()


async def count_versions(db: AsyncSession, scenario_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count(ScenarioVersion.id)).where(
                    ScenarioVersion.scenario_id == scenario_id
                )
            )
        ).scalar()
        or 0
    )


async def submitted_steps(
    db: AsyncSession, scenario: Scenario
) -> list[dict[str, Any]]:
    """The chain scoring must use: the exact version the participant submitted."""
    if scenario.submitted_version_id is not None:
        version = (
            await db.execute(
                select(ScenarioVersion).where(
                    ScenarioVersion.id == scenario.submitted_version_id
                )
            )
        ).scalars().first()
        if version is not None:
            return list(version.steps or [])
    return list(scenario.steps or [])


def version_summary(
    version: ScenarioVersion,
    *,
    is_current: bool,
    is_submitted: bool,
) -> dict[str, Any]:
    snapshot = version.resource_snapshot or {}
    after = snapshot.get("resources_after") or {}
    return {
        "id": version.id,
        "revision": version.revision,
        "label": version.label,
        "step_count": len(version.steps or []),
        "created_at": version.created_at,
        "created_by_user_id": version.created_by_user_id,
        "restored_from_revision": version.restored_from_revision,
        "is_current": is_current,
        "is_submitted": is_submitted,
        "valid": bool(snapshot.get("valid")),
        "goal_reached": bool((snapshot.get("objective") or {}).get("reached")),
        "balance_after": after.get("balance"),
        "energy_after": after.get("energy"),
        "time_after": after.get("time"),
        "available_steps_after": after.get("available_steps"),
    }
