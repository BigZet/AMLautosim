from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import get_current_admin
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.models.leaderboard_adjustments import LeaderboardAdjustment
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    AuditEventOut,
    AuditPageOut,
    LeaderboardAdjustmentIn,
    PlayerDetailOut,
    PlayerDetailUserOut,
    PlayerSummaryOut,
    RoundAdminOut,
    RoundCreateIn,
    RoundStatsOut,
    RoundUpdateIn,
    ScoringSummaryOut,
)
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut
from src.aml_workshop_simulator.services.action_parameters import (
    action_fields_for,
    context_fields_for,
)
from src.aml_workshop_simulator.services.local_rules import ACTION_CARDS
from src.aml_workshop_simulator.services.scoring import score_steps

router = APIRouter()


@router.get("/action-cards", response_model=list[ActionCardOut])
async def get_all_action_cards(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ActionCardOut]:
    cards_stmt = select(ActionCard).order_by(ActionCard.id)
    cards_res = await db.execute(cards_stmt)
    cards = cards_res.scalars().all()

    cards_out = []
    for c in cards:
        code = c.code
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
                costs={"energy": c.energy_cost, "time": c.time_cost, "trust": c.trust_cost},
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


@router.post("/rounds", response_model=RoundAdminOut,
             status_code=status.HTTP_201_CREATED)
async def create_round(
    payload: RoundCreateIn,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    now = datetime.now(timezone.utc)
    round_obj = Round(
        title=payload.title,
        status="draft",
        config_revision=1,
        game_config=payload.game_config,
        scoring_summary=None,
        created_by_user_id=admin.id,
        created_at=now,
        activated_at=None,
        completed_at=None,
    )
    db.add(round_obj)
    await db.commit()
    await db.refresh(round_obj)

    # Audit event
    audit = AuditEvent(
        actor_user_id=admin.id,
        round_id=round_obj.id,
        event_type="round_created",
        target_type="round",
        target_id=str(round_obj.id),
        reason="Admin created new round draft",
        created_at=now,
    )
    db.add(audit)
    await db.commit()

    return round_obj


@router.get("/rounds", response_model=list[RoundAdminOut])
async def list_rounds(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[RoundAdminOut]:
    stmt = select(Round).order_by(desc(Round.id))
    rounds = (await db.execute(stmt)).scalars().all()
    return list(rounds)


@router.get("/rounds/{round_id}", response_model=RoundAdminOut)
async def get_round(
    round_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")
    return round_obj


@router.put("/rounds/{round_id}", response_model=RoundAdminOut)
async def update_round_config(
    round_id: int,
    payload: RoundUpdateIn,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")
    if round_obj.status != "draft":
        raise HTTPException(status_code=409, detail="round_config_locked")
    if round_obj.config_revision != payload.expected_config_revision:
        raise HTTPException(status_code=409, detail="round_config_conflict")

    if payload.title:
        round_obj.title = payload.title
    if payload.game_config:
        round_obj.game_config = payload.game_config
    round_obj.config_revision += 1

    await db.commit()
    await db.refresh(round_obj)
    return round_obj


@router.post("/rounds/{round_id}/activate", response_model=RoundAdminOut)
async def activate_round(
    round_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")

    if round_obj.status == "active":
        return round_obj

    # Check if another round is active
    active_stmt = select(Round).where(Round.status.in_(["active", "scoring"]))
    active_exists = (await db.execute(active_stmt)).scalars().first()
    if active_exists and active_exists.id != round_obj.id:
        raise HTTPException(status_code=409, detail="active_round_exists")

    now = datetime.now(timezone.utc)
    round_obj.status = "active"
    round_obj.activated_at = now

    audit = AuditEvent(
        actor_user_id=admin.id,
        round_id=round_obj.id,
        event_type="round_activated",
        target_type="round",
        target_id=str(round_obj.id),
        reason="Admin activated round",
        created_at=now,
    )
    db.add(audit)
    await db.commit()
    await db.refresh(round_obj)
    return round_obj


@router.post("/rounds/{round_id}/score", response_model=ScoringSummaryOut)
async def trigger_scoring(
    round_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScoringSummaryOut:
    round_stmt = select(Round).where(Round.id == round_id)
    round_obj = (await db.execute(round_stmt)).scalars().first()
    if not round_obj:
        raise HTTPException(status_code=404, detail="round_not_found")

    if round_obj.status == "completed" and round_obj.scoring_summary:
        s = round_obj.scoring_summary
        return ScoringSummaryOut(
            round_id=round_obj.id,
            status=round_obj.status,
            submitted_count=s.get("submitted_count", 0),
            scored_count=s.get("scored_count", 0),
            excluded_draft_count=s.get("excluded_draft_count", 0),
            duration_ms=s.get("duration_ms", 0),
            scoring_version=s.get("scoring_version", "risk-rules-v2"),
            leaderboard_version=s.get("leaderboard_version", "leaderboard-v1"),
            completed_at=round_obj.completed_at or datetime.now(timezone.utc),
        )

    # Fetch submitted scenarios
    start_time = time.time()
    scenarios_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.status == "submitted")
    scenarios = (await db.execute(scenarios_stmt)).scalars().all()

    draft_count_stmt = select(
        func.count(
            Scenario.id)).where(
        Scenario.round_id == round_id,
        Scenario.status == "draft")
    draft_count = (await db.execute(draft_count_stmt)).scalar() or 0

    if not scenarios:
        raise HTTPException(status_code=400, detail="no_submissions")

    card_weights = {
        card["code"]: float(
            card["risk_weight"]) for card in ACTION_CARDS}
    now = datetime.now(timezone.utc)
    scored_count = 0

    for scen in scenarios:
        risk_score, risk_label, explanation = score_steps(
            scen.steps or [], card_weights)
        res_snapshot = scen.resource_snapshot or {}
        resource_score = float(res_snapshot.get("resource_score", 50.0))
        stealth_score = round(max(0.0, 100.0 - risk_score), 1)

        # Composite game score: 60% stealth + 40% resources
        game_score = round((stealth_score * 0.6) + (resource_score * 0.4), 1)

        # Check existing result or create new
        existing_res = (await db.execute(select(ScoringResult).where(ScoringResult.scenario_id == scen.id))).scalars().first()
        if not existing_res:
            res_obj = ScoringResult(
                scenario_id=scen.id,
                risk_score=Decimal(str(risk_score)),
                risk_label=risk_label.value,
                stealth_score=Decimal(str(stealth_score)),
                resource_score=Decimal(str(resource_score)),
                game_score=Decimal(str(game_score)),
                explanation=explanation,
                scoring_version="risk-rules-v2",
                leaderboard_version="leaderboard-v1",
                created_at=now,
            )
            db.add(res_obj)
        else:
            existing_res.risk_score = Decimal(str(risk_score))
            existing_res.risk_label = risk_label.value
            existing_res.stealth_score = Decimal(str(stealth_score))
            existing_res.resource_score = Decimal(str(resource_score))
            existing_res.game_score = Decimal(str(game_score))
            existing_res.explanation = explanation

        scen.status = "scored"
        scored_count += 1

    duration_ms = int((time.time() - start_time) * 1000)
    round_obj.status = "completed"
    round_obj.completed_at = now
    round_obj.scoring_summary = {
        "submitted_count": len(scenarios),
        "scored_count": scored_count,
        "excluded_draft_count": draft_count,
        "duration_ms": duration_ms,
        "scoring_version": "risk-rules-v2",
        "leaderboard_version": "leaderboard-v1",
        "completed_at": now.isoformat(),
    }

    audit = AuditEvent(
        actor_user_id=admin.id,
        round_id=round_obj.id,
        event_type="round_scored",
        target_type="round",
        target_id=str(round_obj.id),
        reason=f"Batch scored {scored_count} scenarios",
        created_at=now,
    )
    db.add(audit)
    await db.commit()

    return ScoringSummaryOut(
        round_id=round_obj.id,
        status="completed",
        submitted_count=len(scenarios),
        scored_count=scored_count,
        excluded_draft_count=draft_count,
        duration_ms=duration_ms,
        scoring_version="risk-rules-v2",
        leaderboard_version="leaderboard-v1",
        completed_at=now,
    )


@router.get("/rounds/{round_id}/stats", response_model=RoundStatsOut)
async def get_round_stats(
    round_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundStatsOut:
    users_total = (await db.execute(select(func.count(User.id)).where(User.role == "participant"))).scalar() or 0
    blocked_total = (await db.execute(select(func.count(User.id)).where(User.role == "participant", User.is_blocked))).scalar() or 0
    active_users = users_total - blocked_total

    draft_scen = (await db.execute(select(func.count(Scenario.id)).where(Scenario.round_id == round_id, Scenario.status == "draft"))).scalar() or 0
    sub_scen = (await db.execute(select(func.count(Scenario.id)).where(Scenario.round_id == round_id, Scenario.status == "submitted"))).scalar() or 0
    scored_scen = (await db.execute(select(func.count(Scenario.id)).where(Scenario.round_id == round_id, Scenario.status == "scored"))).scalar() or 0

    with_scen = draft_scen + sub_scen + scored_scen
    without_scen = max(0, users_total - with_scen)

    last_update = (await db.execute(select(func.max(Scenario.updated_at)).where(Scenario.round_id == round_id))).scalar()

    return RoundStatsOut(
        registered_users=users_total,
        active_users=active_users,
        blocked_users=blocked_total,
        without_scenario=without_scen,
        draft_scenarios=draft_scen,
        submitted_scenarios=sub_scen,
        scored_scenarios=scored_scen,
        public_leaderboard_rows=scored_scen,
        last_scenario_update_at=last_update,
    )


@router.get("/rounds/{round_id}/participants",
            response_model=list[PlayerSummaryOut])
async def list_participants(
    round_id: int,
    query: Optional[str] = Query(None),
    access: Optional[str] = Query("all"),
    scenario_status: Optional[str] = Query(None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[PlayerSummaryOut]:
    stmt = (
        select(
            User,
            Scenario,
            ScoringResult) .outerjoin(
            Scenario,
            (User.id == Scenario.participant_id) & (
                Scenario.round_id == round_id)) .outerjoin(
                    ScoringResult,
                    Scenario.id == ScoringResult.scenario_id) .where(
                        User.role == "participant") .order_by(
                            User.id))
    if access == "active":
        stmt = stmt.where(User.is_blocked == False)
    elif access == "blocked":
        stmt = stmt.where(User.is_blocked)

    if query:
        q_norm = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            (func.lower(
                User.email).like(q_norm)) | (
                func.lower(
                    User.display_name).like(q_norm)))

    records = (await db.execute(stmt)).all()

    results = []
    for user_obj, scen_obj, sr_obj in records:
        if scenario_status and (
                not scen_obj or scen_obj.status != scenario_status):
            continue
        results.append(
            PlayerSummaryOut(
                id=user_obj.id,
                email=user_obj.email,
                display_name=user_obj.display_name or user_obj.email,
                role=user_obj.role,
                is_blocked=user_obj.is_blocked,
                scenario_status=scen_obj.status if scen_obj else "none",
                game_score=str(sr_obj.game_score) if sr_obj else None,
                risk_label=sr_obj.risk_label if sr_obj else None,
                last_login_at=user_obj.last_login_at,
            )
        )
    return results


@router.get("/rounds/{round_id}/participants/{participant_id}",
            response_model=PlayerDetailOut)
async def get_participant_detail(
    round_id: int,
    participant_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerDetailOut:
    user_stmt = select(User).where(User.id == participant_id)
    user_obj = (await db.execute(user_stmt)).scalars().first()
    if not user_obj:
        raise HTTPException(status_code=404, detail="participant_not_found")

    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == participant_id)
    scen_obj = (await db.execute(scen_stmt)).scalars().first()

    result_payload = None
    if scen_obj:
        sr_stmt = select(ScoringResult).where(
            ScoringResult.scenario_id == scen_obj.id)
        sr = (await db.execute(sr_stmt)).scalars().first()
        adj_stmt = select(LeaderboardAdjustment).where(
            LeaderboardAdjustment.scenario_id == scen_obj.id)
        adj = (await db.execute(adj_stmt)).scalars().first()

        if sr:
            result_payload = {
                "base": {
                    "risk_score": str(
                        sr.risk_score),
                    "risk_label": sr.risk_label,
                    "stealth_score": str(
                        sr.stealth_score),
                    "resource_score": str(
                        sr.resource_score),
                    "game_score": str(
                        sr.game_score),
                },
                "effective": {
                    "risk_score": str(
                        adj.risk_score_override) if (
                        adj and adj.risk_score_override is not None) else str(
                        sr.risk_score),
                    "resource_score": str(
                        adj.resource_score_override) if (
                        adj and adj.resource_score_override is not None) else str(
                        sr.resource_score),
                    "game_score": str(
                        adj.game_score_override) if (
                        adj and adj.game_score_override is not None) else str(
                        sr.game_score),
                },
                "explanation": sr.explanation,
                "adjustment": {
                    "revision": adj.revision,
                    "reason": adj.reason,
                    "risk_score_override": str(
                        adj.risk_score_override) if adj.risk_score_override is not None else None,
                    "game_score_override": str(
                        adj.game_score_override) if adj.game_score_override is not None else None,
                } if adj else None,
            }

    # Audit activity
    audit_stmt = select(AuditEvent).where(
        ((AuditEvent.scenario_id == (
            scen_obj.id if scen_obj else -
            1)) | (
            AuditEvent.target_id == str(participant_id)))).order_by(
                desc(
                    AuditEvent.created_at)).limit(10)
    audit_rows = (await db.execute(audit_stmt)).scalars().all()

    return PlayerDetailOut(
        user=PlayerDetailUserOut(
            id=user_obj.id,
            email=user_obj.email,
            display_name=user_obj.display_name or user_obj.email,
            is_blocked=user_obj.is_blocked,
            access_revision=user_obj.access_revision,
            created_at=user_obj.created_at,
            last_login_at=user_obj.last_login_at,
        ),
        scenario={
            "id": scen_obj.id,
            "status": scen_obj.status,
            "revision": scen_obj.revision,
            "steps": scen_obj.steps,
            "resources": scen_obj.resource_snapshot,
            "updated_at": scen_obj.updated_at.isoformat() if scen_obj.updated_at else None,
            "submitted_at": scen_obj.submitted_at.isoformat() if scen_obj.submitted_at else None,
        } if scen_obj else None,
        result=result_payload,
        recent_activity=[
            {"event_type": a.event_type, "reason": a.reason, "created_at": a.created_at.isoformat()}
            for a in audit_rows
        ],
    )


@router.put("/rounds/{round_id}/participants/{participant_id}/access",
            response_model=PlayerSummaryOut)
async def update_participant_access(
    round_id: int,
    participant_id: int,
    payload: AccessUpdateIn,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerSummaryOut:
    if admin.id == participant_id:
        raise HTTPException(status_code=400, detail="self_block_prohibited")

    user_stmt = select(User).where(User.id == participant_id)
    user_obj = (await db.execute(user_stmt)).scalars().first()
    if not user_obj:
        raise HTTPException(status_code=404, detail="participant_not_found")

    if payload.expected_access_revision > 0 and user_obj.access_revision != payload.expected_access_revision:
        raise HTTPException(
            status_code=409,
            detail="participant_access_conflict")

    now = datetime.now(timezone.utc)
    user_obj.is_blocked = payload.blocked
    user_obj.blocked_reason = payload.reason if payload.blocked else None
    user_obj.blocked_at = now if payload.blocked else None
    user_obj.blocked_by_user_id = admin.id if payload.blocked else None
    user_obj.access_revision += 1

    # Revoke sessions if blocked
    if payload.blocked:
        await db.execute(
            update(Session)
            .where(Session.user_id == participant_id, Session.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="blocked", revoked_by_user_id=admin.id)
        )

    # Audit event
    event_type = "participant_blocked" if payload.blocked else "participant_unblocked"
    audit = AuditEvent(
        actor_user_id=admin.id,
        round_id=round_id,
        event_type=event_type,
        target_type="user",
        target_id=str(participant_id),
        reason=payload.reason,
        created_at=now,
    )
    db.add(audit)
    await db.commit()
    await db.refresh(user_obj)

    return PlayerSummaryOut(
        id=user_obj.id,
        email=user_obj.email,
        display_name=user_obj.display_name or user_obj.email,
        role=user_obj.role,
        is_blocked=user_obj.is_blocked,
        last_login_at=user_obj.last_login_at,
    )


@router.put("/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment")
async def adjust_leaderboard(
    round_id: int,
    participant_id: int,
    payload: LeaderboardAdjustmentIn,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == participant_id)
    scen_obj = (await db.execute(scen_stmt)).scalars().first()
    if not scen_obj:
        raise HTTPException(status_code=404, detail="scenario_not_found")

    sr_stmt = select(ScoringResult).where(
        ScoringResult.scenario_id == scen_obj.id)
    sr = (await db.execute(sr_stmt)).scalars().first()
    if not sr:
        raise HTTPException(status_code=409, detail="result_not_available")

    adj_stmt = select(LeaderboardAdjustment).where(
        LeaderboardAdjustment.scenario_id == scen_obj.id)
    adj = (await db.execute(adj_stmt)).scalars().first()

    now = datetime.now(timezone.utc)
    if not adj:
        adj = LeaderboardAdjustment(
            scenario_id=scen_obj.id,
            admin_user_id=admin.id,
            revision=1,
            risk_score_override=Decimal(
                payload.risk_score_override) if payload.risk_score_override else None,
            resource_score_override=Decimal(
                payload.resource_score_override) if payload.resource_score_override else None,
            game_score_override=Decimal(
                payload.game_score_override) if payload.game_score_override else None,
            reason=payload.reason,
            updated_at=now,
        )
        db.add(adj)
    else:
        if payload.expected_revision > 0 and adj.revision != payload.expected_revision:
            raise HTTPException(
                status_code=409,
                detail="adjustment_revision_conflict")
        adj.risk_score_override = Decimal(
            payload.risk_score_override) if payload.risk_score_override else None
        adj.resource_score_override = Decimal(
            payload.resource_score_override) if payload.resource_score_override else None
        adj.game_score_override = Decimal(
            payload.game_score_override) if payload.game_score_override else None
        adj.reason = payload.reason
        adj.revision += 1
        adj.updated_at = now

    audit = AuditEvent(
        actor_user_id=admin.id,
        round_id=round_id,
        scenario_id=scen_obj.id,
        event_type="leaderboard_adjusted",
        target_type="scenario",
        target_id=str(scen_obj.id),
        reason=payload.reason,
        created_at=now,
    )
    db.add(audit)
    await db.commit()

    return {"status": "ok", "revision": adj.revision}


@router.delete(
    "/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment",
    status_code=status.HTTP_204_NO_CONTENT)
async def clear_leaderboard_adjustment(
    round_id: int,
    participant_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    scen_stmt = select(Scenario).where(
        Scenario.round_id == round_id,
        Scenario.participant_id == participant_id)
    scen_obj = (await db.execute(scen_stmt)).scalars().first()
    if not scen_obj:
        return

    adj_stmt = select(LeaderboardAdjustment).where(
        LeaderboardAdjustment.scenario_id == scen_obj.id)
    adj = (await db.execute(adj_stmt)).scalars().first()
    if adj:
        now = datetime.now(timezone.utc)
        audit = AuditEvent(
            actor_user_id=admin.id,
            round_id=round_id,
            scenario_id=scen_obj.id,
            event_type="leaderboard_adjustment_cleared",
            target_type="scenario",
            target_id=str(scen_obj.id),
            reason="Admin cleared leaderboard adjustment",
            created_at=now,
        )
        db.add(audit)
        await db.delete(adj)
        await db.commit()


@router.get("/rounds/{round_id}/audit-events", response_model=AuditPageOut)
async def list_audit_events(
    round_id: int,
    event_type: Optional[str] = Query(None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditPageOut:
    stmt = select(AuditEvent).where(
        AuditEvent.round_id == round_id).order_by(
        desc(
            AuditEvent.created_at)).limit(100)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    events = (await db.execute(stmt)).scalars().all()

    rows = [
        AuditEventOut(
            id=e.id,
            actor_user_id=e.actor_user_id,
            round_id=e.round_id,
            scenario_id=e.scenario_id,
            event_type=e.event_type,
            target_type=e.target_type,
            target_id=e.target_id,
            reason=e.reason,
            request_id=e.request_id,
            metadata=e.metadata_,
            created_at=e.created_at,
        )
        for e in events
    ]
    return AuditPageOut(rows=rows, next_cursor=None)
