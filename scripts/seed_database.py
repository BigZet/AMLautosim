"""Idempotent database bootstrap.

Running it repeatedly leaves exactly one row per card version, one bootstrap
administrator and one demo round draft. Nothing is duplicated and no existing
participant data is touched.

    python -m scripts.seed_database --migrate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aml_workshop_simulator.core.config import settings  # noqa: E402
from src.aml_workshop_simulator.core.game_config import load_config  # noqa: E402
from src.aml_workshop_simulator.core.security import (  # noqa: E402
    get_password_hash,
    verify_password,
)
from src.aml_workshop_simulator.db.models.action_cards import ActionCard  # noqa: E402
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent  # noqa: E402
from src.aml_workshop_simulator.db.models.rounds import Round  # noqa: E402
from src.aml_workshop_simulator.db.models.users import User  # noqa: E402
from src.aml_workshop_simulator.db.session import (  # noqa: E402
    AsyncSessionLocal,
    async_engine,
)
from src.aml_workshop_simulator.domain.catalog import (  # noqa: E402
    CARD_CATALOG,
    build_parameter_schema,
)
from src.aml_workshop_simulator.domain.rules import REFERENCE_GAME_CONFIG  # noqa: E402
from src.aml_workshop_simulator.services.configuration import (  # noqa: E402
    freeze_game_config,
)

DEMO_ROUND_TITLE = load_config("bootstrap.json")["demo_round_title"]


async def wait_for_db(timeout_seconds: int = 60) -> None:
    """Block until PostgreSQL answers, leaving no connection in the pool.

    `main` drives several `asyncio.run` calls, each with its own event loop. A
    connection kept by the pool here would be handed to the next loop and fail
    with "attached to a different loop", so the engine is disposed before this
    loop closes.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    try:
        while time.monotonic() < deadline:
            try:
                async with async_engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.0)
        raise RuntimeError(f"database not reachable: {last_error}")
    finally:
        await async_engine.dispose()


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


async def seed_cards(db: AsyncSession) -> list[ActionCard]:
    """Insert or refresh the catalog and remove obsolete card versions."""
    # Freeze existing rounds before catalog refresh (including the first upgrade
    # from versions that stored only card references). Never rewrite their rules.
    old_cards = list((await db.execute(select(ActionCard))).scalars().all())
    rounds = list((await db.execute(select(Round).with_for_update())).scalars().all())
    for round_obj in rounds:
        # An installation upgraded across a catalog reduction carries rounds
        # that name card versions this build no longer ships. Refusing to
        # freeze them would abort the seed and, because the API container runs
        # the seed before uvicorn, the service would never start again. Drop the
        # dead references instead -- `RoundPolicy` already skips them at play
        # time -- and say out loud what was dropped.
        dropped: list[tuple[str, int]] = []
        config = freeze_game_config(
            round_obj.game_config, old_cards, strict=False, dropped=dropped
        )
        if dropped:
            print(
                f"seed: round {round_obj.id}: dropped card versions no longer in "
                f"the catalog: {', '.join(f'{code} v{version}' for code, version in dropped)}",
                file=sys.stderr,
            )
        if not config.get("card_snapshots"):
            print(
                f"seed: round {round_obj.id}: left unfrozen, none of its card "
                "versions still exist in the catalog",
                file=sys.stderr,
            )
        if "config_version" in config:
            from src.aml_workshop_simulator.api.routers.admin.common import (
                config_version,
            )
            config["config_version"] = config_version(config)
        if config != round_obj.game_config:
            round_obj.game_config = config
    now = datetime.now(UTC)
    result: list[ActionCard] = []
    catalog_keys = [(entry["code"], entry["version"]) for entry in CARD_CATALOG]
    await db.execute(
        delete(ActionCard).where(
            tuple_(ActionCard.code, ActionCard.version).not_in(catalog_keys)
        )
    )
    for entry in CARD_CATALOG:
        card = (
            await db.execute(
                select(ActionCard).where(
                    ActionCard.code == entry["code"],
                    ActionCard.version == entry["version"],
                )
            )
        ).scalars().first()
        schema = build_parameter_schema(entry)
        if card is None:
            card = ActionCard(
                code=entry["code"],
                version=entry["version"],
                title=entry["title"],
                category=entry["category"],
                flow=entry["flow"],
                risk_weight=entry["risk_weight"],
                energy_cost=entry["energy_cost"],
                time_cost=entry["time_cost"],
                fee_rate=entry["fee_rate"],
                min_amount=entry["min_amount"],
                max_amount=entry["max_amount"],
                max_frequency=entry["max_frequency"],
                requires_card_code=entry["requires_card_code"],
                parameter_schema=schema,
                is_active=True,
                created_at=now,
            )
            db.add(card)
        else:
            card.title = entry["title"]
            card.category = entry["category"]
            card.flow = entry["flow"]
            card.risk_weight = entry["risk_weight"]
            card.energy_cost = entry["energy_cost"]
            card.time_cost = entry["time_cost"]
            card.fee_rate = entry["fee_rate"]
            card.min_amount = entry["min_amount"]
            card.max_amount = entry["max_amount"]
            card.max_frequency = entry["max_frequency"]
            card.requires_card_code = entry["requires_card_code"]
            card.parameter_schema = schema
            card.is_active = True
        result.append(card)
    await db.flush()
    return result


async def seed_admin(db: AsyncSession) -> User:
    email = settings.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
    admin = (await db.execute(select(User).where(User.email == email))).scalars().first()
    now = datetime.now(UTC)
    if admin is not None:
        # `.env.example` asks the operator to change this from any value that has
        # ever been committed. Creating the account and then ignoring the setting
        # made that instruction impossible to follow after the first run.
        if not verify_password(settings.BOOTSTRAP_ADMIN_PASSWORD, admin.hashed_password):
            admin.hashed_password = get_password_hash(settings.BOOTSTRAP_ADMIN_PASSWORD)
            admin.failed_login_count = 0
            admin.locked_until = None
            admin.updated_at = now
            print("seed: bootstrap administrator password updated", file=sys.stderr)
        return admin

    admin = User(
        email=email,
        display_name="Организатор",
        hashed_password=get_password_hash(settings.BOOTSTRAP_ADMIN_PASSWORD),
        role="admin",
        is_blocked=False,
        access_revision=1,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(admin)
    await db.flush()
    return admin


def reference_game_config(cards: list[ActionCard]) -> dict[str, Any]:
    """Reference configuration pinned to the seeded card rows.

    `operations` decides what is playable; `card_versions` repeats the same set
    so a snapshot written by this seed stays readable by the older loader.
    """
    from copy import deepcopy
    config = deepcopy(REFERENCE_GAME_CONFIG)
    enabled = {
        (str(item["code"]), int(item.get("version", 1)))
        for item in config.get("operations", [])
    }
    config["card_versions"] = [
        {"id": card.id, "code": card.code, "version": card.version}
        for card in cards
        if (card.code, card.version) in enabled
    ]
    return freeze_game_config(config, cards)


async def seed_demo_round(db: AsyncSession, admin: User, cards: list[ActionCard]) -> Round:
    round_obj = (
        await db.execute(select(Round).where(Round.title == DEMO_ROUND_TITLE))
    ).scalars().first()
    if round_obj is not None:
        return round_obj
    now = datetime.now(UTC)
    round_obj = Round(
        title=DEMO_ROUND_TITLE,
        status="draft",
        config_revision=1,
        game_config=reference_game_config(cards),
        created_by_user_id=admin.id,
        created_at=now,
    )
    db.add(round_obj)
    await db.flush()
    # The audit trail must show how the round came to exist, even when it was
    # created by the seed rather than by an administrator command.
    db.add(
        AuditEvent(
            actor_user_id=admin.id,
            round_id=round_obj.id,
            event_type="round_created",
            target_type="round",
            target_id=str(round_obj.id),
            reason="Seeded demo round",
            created_at=now,
        )
    )
    await db.flush()
    return round_obj


async def seed(activate_round: bool = False) -> dict[str, Any]:
    from src.aml_workshop_simulator.schemas.catalog_config import (
        validate_configuration_files,
    )
    validate_configuration_files()
    async with AsyncSessionLocal() as db:
        cards = await seed_cards(db)
        admin = await seed_admin(db)
        round_obj = await seed_demo_round(db, admin, cards)
        if activate_round and round_obj.status == "draft":
            other = (
                await db.execute(
                    select(Round).where(Round.status.in_(["active", "scoring"]))
                )
            ).scalars().first()
            if other is None:
                config = dict(round_obj.game_config)
                from src.aml_workshop_simulator.api.routers.admin.common import (
                    config_version,
                )

                config["config_version"] = config_version(config)
                activated_at = datetime.now(UTC)
                round_obj.game_config = config
                round_obj.status = "active"
                round_obj.activated_at = activated_at
                db.add(
                    AuditEvent(
                        actor_user_id=admin.id,
                        round_id=round_obj.id,
                        event_type="round_activated",
                        target_type="round",
                        target_id=str(round_obj.id),
                        reason="Seeded demo round activated",
                        metadata_={"config_version": config["config_version"]},
                        created_at=activated_at,
                    )
                )
        await db.commit()
        return {
            "cards": len(cards),
            "admin_id": admin.id,
            "round_id": round_obj.id,
            "round_status": round_obj.status,
        }


async def _seed_and_dispose(activate_round: bool) -> dict[str, Any]:
    summary = await seed(activate_round=activate_round)
    await async_engine.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AML simulator database")
    parser.add_argument("--migrate", action="store_true", help="run alembic upgrade head first")
    parser.add_argument("--wait-for-db", action="store_true", help="wait until PostgreSQL answers")
    parser.add_argument(
        "--activate-round",
        action="store_true",
        help="activate the demo round when no other round is active",
    )
    args = parser.parse_args()
    if args.wait_for_db:
        asyncio.run(wait_for_db())
    if args.migrate:
        # Alembic opens its own event loop, so migrations must run outside ours.
        run_migrations()
    summary = asyncio.run(_seed_and_dispose(args.activate_round))
    print(
        "seed complete: "
        f"cards={summary['cards']} admin_id={summary['admin_id']} "
        f"round_id={summary['round_id']} status={summary['round_status']}"
    )


if __name__ == "__main__":
    main()
