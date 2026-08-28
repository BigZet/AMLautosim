from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import (
    get_current_user,
    get_current_user_optional,
)
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.leaderboard_adjustments import LeaderboardAdjustment
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.leaderboard import (
    BaseResultOut,
    LeaderboardMetaOut,
    LeaderboardPageOut,
    LeaderboardRowOut,
    ResultOut,
)
from src.aml_workshop_simulator.schemas.rounds import (
    ActionCardOut,
    RoundPublicOut,
    RoundSummaryOut,
    RoundSummaryPageOut,
)
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
    ScenarioPutIn,
    ScenarioSubmitIn,
)
from src.aml_workshop_simulator.services.action_parameters import (
    action_fields_for,
    context_fields_for,
)
from src.aml_workshop_simulator.services.local_rules import ACTION_CARDS
from src.aml_workshop_simulator.services.scenario_service import calculate_resource_snapshot

router = APIRouter()


@router.get("/active", response_model=Optional[RoundPublicOut])
async def get_active_round(
    db: AsyncSession = Depends(get_db),
) -> Optional[RoundPublicOut]:
    stmt = select(Round).where(Round.status == "active")
    res = await db.execute(stmt)
    round_obj = res.scalars().first()
    if not round_obj:
        return None
    return RoundPublicOut(
        id=round_obj.id,
        title=round_obj.title,
        status=round_obj.status,
        config_version=round_obj.game_config.get("config_version"),
        activated_at=round_obj.activated_at,
        game_config=round_obj.game_config,
    )


@router.get("/mine", response_model=RoundSummaryPageOut)
async def get_my_rounds(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundSummaryPageOut:
    # 1. Fetch active round
    active_stmt = select(Round).where(Round.status == "active")
    active_round = (await db.execute(active_stmt)).scalars().first()

    # 2. Fetch rounds where user has a scenario
    scenarios_stmt = select(
        Scenario,
        Round).join(
        Round,
        Scenario.round_id == Round.id).where(
            Scenario.participant_id == current_user.id).order_by(
                desc(
                    Round.id))
    scenarios_res = await db.execute(scenarios_stmt)
    rows_data = scenarios_res.all()

    seen_round_ids = set()
    summary_rows: list[RoundSummaryOut] = []

    if active_round:
        seen_round_ids.add(active_round.id)
        # Check scenario
        scen = next((s for s, r in rows_data if r.id == active_round.id), None)
        summary_rows.append(
            RoundSummaryOut(
                id=active_round.id,
                title=active_round.title,
                status=active_round.status,
                scenario_status=scen.status if scen else None,
                result_available=False,
                completed_at=None,
            )
        )

    for scen, round_obj in rows_data:
        if round_obj.id in seen_round_ids:
            continue
        seen_round_ids.add(round_obj.id)
        summary_rows.append(
            RoundSummaryOut(
                id=round_obj.id,
                title=round_obj.title,
                status=round_obj.status,
                scenario_status=scen.status,
                result_available=(
                    round_obj.status == "completed" and scen.status == "scored"),
                completed_at=round_obj.completed_at,
            ))

    return RoundSummaryPageOut(rows=summary_rows, next_cursor=None)


@router.get("/{round_id}/cards", response_model=list[ActionCardOut])
async def get_round_cards(
    round_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ActionCardOut]:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")

    cards_stmt = select(ActionCard).where(ActionCard.is_active)
    cards_res = await db.execute(cards_stmt)
    cards = cards_res.scalars().all()

    cards_out: list[ActionCardOut] = []
    for c in cards:
        code = c.code
        # Lookup channel & limits from domain config
        local_card = next(
            (item for item in ACTION_CARDS if item["code"] == code), None)
        channels = local_card["channels"] if local_card else [
            "bank", "mobile", "web"]
        freq_limit = local_card["round_frequency_limit"] if local_card else 3
        description = local_card["description"] if local_card else ""

        cards_out.append(
            ActionCardOut(
                id=c.id,
                code=c.code,
                version=c.version,
                title=c.title,
                description=description,
                category=c.category,
                flow=c.flow,
                risk_weight=str(c.risk_weight),
                costs={
                    "energy": c.energy_cost,
                    "time": c.time_cost,
                    "trust": c.trust_cost,
                },
                fee_rate=str(c.fee_rate),
                min_amount=str(c.min_amount),
                max_amount=str(c.max_amount),
                max_frequency=c.max_frequency,
                round_frequency_limit=freq_limit,
                requires_card_code=c.requires_card_code,
                channels=channels,
                fields=[dict(f) for f in action_fields_for(code)],
                context_fields=[dict(f) for f in context_fields_for(code)],
            )
        )
    return cards_out


@router.get("/{round_id}/scenario", response_model=Optional[ScenarioOut])
async def get_my_scenario(
    round_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[ScenarioOut]:
    stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == current_user.id,
    )
    scen = (await db.execute(stmt)).scalars().first()
    if not scen:
        return None
    return ScenarioOut(
        id=scen.id,
        round_id=scen.round_id,
        participant_id=scen.participant_id,
        status=scen.status,
        revision=scen.revision,
        steps=scen.steps or [],
        resources=scen.resource_snapshot or {},
        updated_at=scen.updated_at,
        submitted_at=scen.submitted_at,
    )


@router.put("/{round_id}/scenario", response_model=ScenarioOut)
async def update_scenario_draft(
    round_id: int,
    payload: ScenarioPutIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")
    if round_obj.status != "active":
        raise HTTPException(status_code=409, detail="round_locked")

    # Load existing scenario
    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == current_user.id,
    )
    scen = (await db.execute(scen_stmt)).scalars().first()

    # Convert steps to standardized dict format
    raw_steps = []
    for step in payload.steps:
        s_dict = step.model_dump()
        # Normalize card_code
        if s_dict.get("card") and isinstance(s_dict["card"], dict):
            s_dict["card_code"] = s_dict["card"].get("code", "")
        
        step_chan = s_dict.get("channel") or (s_dict.get("context", {}).get("channel") if isinstance(s_dict.get("context"), dict) else None) or "branch"
        s_dict["channel"] = step_chan
        # Merge flat context if provided
        if not s_dict.get("context"):
            s_dict["context"] = {
                "country_risk": s_dict.get("country_risk") or "low",
                "recipient_type": s_dict.get("recipient_type") or "known_counterparty",
                "time_of_day": s_dict.get("time_of_day") or "day",
                "velocity": s_dict.get("velocity") or "normal",
                "channel": step_chan,
                "has_documents": s_dict.get("has_documents") if s_dict.get("has_documents") is not None else True,
            }
        elif isinstance(s_dict["context"], dict) and "channel" not in s_dict["context"]:
            s_dict["context"]["channel"] = step_chan
        raw_steps.append(s_dict)

    # Calculate resources & validation
    snapshot = calculate_resource_snapshot(raw_steps, round_obj.game_config)

    now = datetime.now(timezone.utc)
    if not scen:
        scen = Scenario(
            round_id=round_id,
            participant_id=current_user.id,
            status="draft",
            steps=raw_steps,
            resource_snapshot=snapshot,
            revision=1,
            updated_at=now,
            submitted_at=None,
        )
        db.add(scen)
    else:
        # Check optimistic revision
        if payload.expected_revision > 0 and scen.revision != payload.expected_revision:
            raise HTTPException(
                status_code=409,
                detail=f"scenario_revision_conflict (expected {
                    payload.expected_revision}, got {
                    scen.revision})",
            )
        scen.steps = raw_steps
        scen.resource_snapshot = snapshot
        scen.revision = scen.revision + 1
        scen.status = "draft"  # Return to draft on edit
        scen.updated_at = now

    await db.commit()
    await db.refresh(scen)

    return ScenarioOut(
        id=scen.id,
        round_id=scen.round_id,
        participant_id=scen.participant_id,
        status=scen.status,
        revision=scen.revision,
        steps=scen.steps or [],
        resources=scen.resource_snapshot or {},
        updated_at=scen.updated_at,
        submitted_at=scen.submitted_at,
    )


@router.post("/{round_id}/scenario/submit", response_model=ScenarioOut)
async def submit_scenario(
    round_id: int,
    payload: ScenarioSubmitIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")
    if round_obj.status != "active":
        raise HTTPException(status_code=409, detail="round_locked")

    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == current_user.id,
    )
    scen = (await db.execute(scen_stmt)).scalars().first()
    if not scen or not scen.steps:
        raise HTTPException(status_code=400, detail="scenario_empty")

    if payload.expected_revision > 0 and scen.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail="scenario_revision_conflict")

    snapshot = calculate_resource_snapshot(scen.steps, round_obj.game_config)
    if not snapshot["valid"]:
        raise HTTPException(
            status_code=400,
            detail=f"scenario_validation_failed: {snapshot['violations'][0]}",
        )
    if not snapshot["goal_reached"]:
        target = round_obj.game_config.get(
            "objectives", {}).get(
            "target_outflow", "150000.00")
        raise HTTPException(
            status_code=400,
            detail=f"target_outflow_not_reached: Необходимо провести минимум {
                float(target):,.0f} ₽ через расходные операции.",
        )

    now = datetime.now(timezone.utc)
    scen.status = "submitted"
    scen.resource_snapshot = snapshot
    scen.submitted_at = now
    scen.updated_at = now

    await db.commit()
    await db.refresh(scen)

    return ScenarioOut(
        id=scen.id,
        round_id=scen.round_id,
        participant_id=scen.participant_id,
        status=scen.status,
        revision=scen.revision,
        steps=scen.steps or [],
        resources=scen.resource_snapshot or {},
        updated_at=scen.updated_at,
        submitted_at=scen.submitted_at,
    )


@router.get("/{round_id}/result", response_model=Optional[ResultOut])
async def get_my_result(
    round_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[ResultOut]:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj or round_obj.status != "completed":
        return None

    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == current_user.id,
    )
    scen = (await db.execute(scen_stmt)).scalars().first()
    if not scen:
        return None

    res_stmt = select(ScoringResult).where(
        ScoringResult.scenario_id == scen.id)
    scoring_res = (await db.execute(res_stmt)).scalars().first()
    if not scoring_res:
        return None

    # Check for leaderboard adjustments
    adj_stmt = select(LeaderboardAdjustment).where(
        LeaderboardAdjustment.scenario_id == scen.id)
    adj = (await db.execute(adj_stmt)).scalars().first()

    effective_game_score = adj.game_score_override if (
        adj and adj.game_score_override is not None) else scoring_res.game_score

    # Compute rank in leaderboard
    all_scores_stmt = select(ScoringResult).join(
        Scenario,
        ScoringResult.scenario_id == Scenario.id).where(
        Scenario.round_id == round_id).order_by(
            desc(
                ScoringResult.game_score))
    all_res = (await db.execute(all_scores_stmt)).scalars().all()
    rank = 1
    for idx, r in enumerate(all_res, start=1):
        if r.scenario_id == scen.id:
            rank = idx
            break

    return ResultOut(
        scenario_id=scen.id,
        base=BaseResultOut(
            risk_score=str(scoring_res.risk_score),
            risk_label=scoring_res.risk_label,
            stealth_score=str(scoring_res.stealth_score),
            resource_score=str(scoring_res.resource_score),
            game_score=str(scoring_res.game_score),
        ),
        leaderboard=LeaderboardMetaOut(
            effective_game_score=str(effective_game_score),
            rank=rank,
            is_adjusted=adj is not None,
        ),
        versions={
            "scoring": scoring_res.scoring_version,
            "leaderboard": scoring_res.leaderboard_version,
        },
        explanation=scoring_res.explanation or {},
    )


@router.get("/{round_id}/leaderboard", response_model=LeaderboardPageOut)
async def get_public_leaderboard(
    round_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardPageOut:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj or round_obj.status != "completed":
        return LeaderboardPageOut(
            rows=[],
            next_cursor=None,
            generated_at=datetime.now(
                timezone.utc))

    # Fetch all scored scenarios along with user, scoring_result, and optional
    # adjustment
    stmt = (
        select(
            Scenario,
            User,
            ScoringResult,
            LeaderboardAdjustment) .join(
            User,
            Scenario.participant_id == User.id) .join(
                ScoringResult,
                Scenario.id == ScoringResult.scenario_id) .outerjoin(
                    LeaderboardAdjustment,
                    Scenario.id == LeaderboardAdjustment.scenario_id) .where(
                        Scenario.round_id == round_id,
                        User.is_blocked == False,
        ))
    res = await db.execute(stmt)
    records = res.all()

    board_entries = []
    for scen, usr, sr, adj in records:
        eff_game_score = float(
            adj.game_score_override) if (
            adj and adj.game_score_override is not None) else float(
            sr.game_score)
        eff_risk_score = float(
            adj.risk_score_override) if (
            adj and adj.risk_score_override is not None) else float(
            sr.risk_score)
        eff_resource_score = float(
            adj.resource_score_override) if (
            adj and adj.resource_score_override is not None) else float(
            sr.resource_score)

        resources = scen.resource_snapshot.get(
            "resources_after", {}) if scen.resource_snapshot else {}
        totals = scen.resource_snapshot.get(
            "totals", {}) if scen.resource_snapshot else {}

        board_entries.append({
            "participant_id": usr.id,
            "display_name": usr.display_name or f"Игрок #{usr.id}",
            "game_score": eff_game_score,
            "stealth_score": float(sr.stealth_score),
            "resource_score": eff_resource_score,
            "risk_score": eff_risk_score,
            "risk_label": sr.risk_label,
            "is_adjusted": adj is not None,
            "is_current_user": bool(current_user and current_user.id == usr.id),
            "balance": resources.get("balance", "0"),
            "energy": resources.get("energy", 0),
            "time": resources.get("time", 0),
            "trust": resources.get("trust", 0),
            "fees": totals.get("fees", "0"),
        })

    # Sort descending by game_score, then ascending by risk_score
    board_entries.sort(
        key=lambda x: (-x["game_score"], x["risk_score"], -x["resource_score"]))

    rows: list[LeaderboardRowOut] = []
    for rank, entry in enumerate(board_entries, start=1):
        rows.append(
            LeaderboardRowOut(
                rank=rank,
                display_name=entry["display_name"],
                game_score=f"{entry['game_score']:.1f}",
                stealth_score=f"{entry['stealth_score']:.1f}",
                resource_score=f"{entry['resource_score']:.1f}",
                risk_score=f"{entry['risk_score']:.1f}",
                risk_label=entry["risk_label"],
                is_adjusted=entry["is_adjusted"],
                is_current_user=entry["is_current_user"],
                balance=entry["balance"],
                energy=entry["energy"],
                time=entry["time"],
                trust=entry["trust"],
                fees=entry["fees"],
            )
        )

    return LeaderboardPageOut(
        rows=rows,
        next_cursor=None,
        generated_at=datetime.now(timezone.utc),
    )
