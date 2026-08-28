"""
Database seed script for AML Workshop Simulator.
Seeds:
- Admin user: admin@aml.local / admin12345
- Participant user: demo@aml.local / demo12345
- Catalog of Action Cards
- Initial Active Round with full reference game config
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.security import get_password_hash
from src.aml_workshop_simulator.db.session import AsyncSessionLocal
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.services.local_rules import (
    ACTION_CARDS,
    INITIAL_BALANCE,
    INITIAL_ENERGY,
    INITIAL_TIME,
    INITIAL_TRUST,
    MAX_ACTIONS,
    MAX_IDENTICAL_STEPS,
    MAX_NIGHT_OPERATIONS,
    ROUND_LIMITS,
    TARGET_OUTFLOW,
)
from src.aml_workshop_simulator.services.action_parameters import (
    action_fields_for,
    context_fields_for,
)


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        print("[1/4] Checking and creating initial Users...")
        # 1. Admin user
        admin_res = await session.execute(select(User).where(User.email == "admin@aml.local"))
        admin_user = admin_res.scalars().first()
        if not admin_user:
            admin_user = User(
                email="admin@aml.local",
                display_name="Организатор Мастер-класса",
                hashed_password=get_password_hash("admin12345"),
                role="admin",
                is_blocked=False,
                access_revision=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(admin_user)
            await session.flush()
            print("  -> Created Admin user: admin@aml.local")
        else:
            print("  -> Admin user already exists")

        # 2. Demo Participant user
        demo_res = await session.execute(select(User).where(User.email == "demo@aml.local"))
        demo_user = demo_res.scalars().first()
        if not demo_user:
            demo_user = User(
                email="demo@aml.local",
                display_name="Финансовый детектив",
                hashed_password=get_password_hash("demo12345"),
                role="participant",
                is_blocked=False,
                access_revision=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(demo_user)
            await session.flush()
            print("  -> Created Demo Participant user: demo@aml.local")

        print("[2/4] Seeding Action Cards catalog...")
        card_versions_config = []
        for card_data in ACTION_CARDS:
            code = card_data["code"]
            version = card_data["version"]
            card_res = await session.execute(
                select(ActionCard).where(ActionCard.code == code, ActionCard.version == version)
            )
            card = card_res.scalars().first()
            
            param_schema = {
                "schema_version": 1,
                "context_fields": [dict(f) for f in context_fields_for(code)],
                "action_fields": [dict(f) for f in action_fields_for(code)],
            }
            
            if not card:
                card = ActionCard(
                    code=code,
                    version=version,
                    title=card_data["title"],
                    category=card_data["category"],
                    flow=card_data["flow"],
                    risk_weight=Decimal(str(card_data["risk_weight"])),
                    energy_cost=card_data["energy_cost"],
                    time_cost=card_data["time_cost"],
                    trust_cost=card_data["trust_cost"],
                    fee_rate=Decimal(str(card_data["fee_rate"])),
                    min_amount=Decimal(str(card_data["min_amount"])),
                    max_amount=Decimal(str(card_data["max_amount"])),
                    max_frequency=card_data["max_frequency"],
                    requires_card_code=card_data["requires_card_code"],
                    parameter_schema=param_schema,
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(card)
                await session.flush()
                print(f"  -> Added card: {code} (v{version})")
            
            card_versions_config.append({"id": card.id, "code": code, "version": version})

        print("[3/4] Checking Active Round...")
        round_res = await session.execute(select(Round).where(Round.status.in_(["active", "draft"])))
        current_round = round_res.scalars().first()

        if not current_round:
            game_config = {
                "schema_version": 2,
                "config_version": "round-config-v1:default",
                "resources": {
                    "initial_balance": str(INITIAL_BALANCE),
                    "initial_energy": INITIAL_ENERGY,
                    "initial_time": INITIAL_TIME,
                    "initial_trust": INITIAL_TRUST,
                },
                "objectives": {
                    "target_outflow": str(TARGET_OUTFLOW),
                    "max_actions": MAX_ACTIONS,
                },
                "constraints": {
                    "max_identical_steps": MAX_IDENTICAL_STEPS,
                    "max_night_operations": MAX_NIGHT_OPERATIONS,
                    "category_limits": {k: str(v["limit"]) for k, v in ROUND_LIMITS.items()},
                },
                "card_versions": card_versions_config,
                "ruleset_version": "game-rules-v2",
                "scoring": {
                    "version": "risk-rules-v2",
                    "review_threshold": "35.00",
                    "suspicious_threshold": "65.00",
                },
                "leaderboard": {
                    "version": "leaderboard-v1",
                    "weights": {"stealth": "0.60", "resources": "0.40"},
                },
            }

            active_round = Round(
                title="Мастер-класс AML: Построение цепочек и обход риск-правил",
                status="active",
                config_revision=1,
                game_config=game_config,
                scoring_summary=None,
                created_by_user_id=admin_user.id,
                created_at=datetime.now(timezone.utc),
                activated_at=datetime.now(timezone.utc),
                completed_at=None,
            )
            session.add(active_round)
            await session.flush()
            print(f"  -> Created and Activated Round ID {active_round.id}: {active_round.title}")
        else:
            print(f"  -> Found existing round ID {current_round.id} with status '{current_round.status}'")

        await session.commit()
        print("[4/4] [SUCCESS] Database seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed())
