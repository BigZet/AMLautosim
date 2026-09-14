"""Autosave and final submission. Each write commits scenario and audit together."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import (
    Conflict,
    ScenarioValidationFailed,
)
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.queries import get_round, get_scenario
from src.aml_workshop_simulator.domain.lifecycle import (
    require_editable,
    require_revision,
)
from src.aml_workshop_simulator.domain.rules import submit_blockers
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
)
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
    ScenarioPreviewIn,
    ScenarioPreviewOut,
    ScenarioPutIn,
    ScenarioSubmitIn,
)
from src.aml_workshop_simulator.services import participant_state
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.projections import scenario_out
from src.aml_workshop_simulator.services.scenario_service import (
    canonical_round_steps,
    load_round_card_specs,
    payload_hash,
    prepare_scenario,
    round_policy,
)


async def read(
    db: AsyncSession, round_id: int, participant_id: int
) -> ScenarioOut | None:
    return (await participant_state.read(db, participant_id, round_id)).scenario


async def preview(
    db: AsyncSession, round_id: int, participant_id: int, payload: ScenarioPreviewIn
) -> ScenarioPreviewOut:
    round_obj = await get_round(db, round_id)
    scenario = await get_scenario(db, round_id, participant_id)
    require_editable(round_obj.status, scenario.status if scenario else None)
    _, snapshot = prepare_scenario(round_obj, payload.steps)
    blockers = submit_blockers(snapshot)
    return ScenarioPreviewOut(
        resources=snapshot, blockers=blockers, can_submit=not blockers
    )


async def save(
    db: AsyncSession, round_id: int, participant_id: int, payload: ScenarioPutIn
) -> ScenarioOut:
    round_obj = await get_round(db, round_id, lock="share")
    scenario = await get_scenario(db, round_id, participant_id, lock=True)
    require_editable(round_obj.status, scenario.status if scenario else None)
    steps, snapshot = prepare_scenario(round_obj, payload.steps)
    digest = payload_hash(steps)
    if scenario and scenario.last_client_mutation_id == payload.client_mutation_id:
        if scenario.payload_hash != digest:
            raise Conflict(
                "Идентификатор сохранения уже использован для другого содержимого.",
                code="mutation_id_reused",
            )
        return scenario_out(scenario)
    require_revision(scenario.revision if scenario else 0, payload.expected_revision)
    if scenario is None:
        scenario = Scenario(
            round_id=round_id,
            participant_id=participant_id,
            status="editing",
            revision=0,
        )
        db.add(scenario)
    # Revision is only a concurrency token, not a version in a history.
    if scenario.payload_hash != digest:
        scenario.revision += 1
    scenario.steps = steps
    scenario.resource_snapshot = snapshot
    scenario.payload_hash = digest
    scenario.last_client_mutation_id = payload.client_mutation_id
    scenario.updated_at = datetime.now(UTC)
    await db.commit()
    return scenario_out(scenario)


async def submit(
    db: AsyncSession,
    round_id: int,
    participant_id: int,
    payload: ScenarioSubmitIn,
    request_id: str | None = None,
) -> ScenarioOut:
    round_obj = await get_round(db, round_id, lock="share")
    scenario = await get_scenario(db, round_id, participant_id, lock=True)
    require_playable_contract(round_obj.game_config)
    if scenario is not None and scenario.status in {"submitted", "scored"}:
        specs = load_round_card_specs(round_obj)
        steps = canonical_round_steps(
            round_obj, payload.steps, specs, round_policy(round_obj, specs)
        )
        if (
            scenario.last_client_mutation_id == payload.client_mutation_id
            and scenario.payload_hash == payload_hash(steps)
        ):
            return scenario_out(scenario)
        raise Conflict(
            "Сценарий уже отправлен. Повторная попытка недоступна.",
            code="scenario_submitted",
        )
    require_editable(round_obj.status, scenario.status if scenario else None)
    require_revision(scenario.revision if scenario else 0, payload.expected_revision)
    steps, snapshot = prepare_scenario(round_obj, payload.steps)
    digest = payload_hash(steps)
    if (
        scenario is not None
        and scenario.last_client_mutation_id == payload.client_mutation_id
        and scenario.payload_hash != digest
    ):
        raise Conflict(
            "Идентификатор команды уже использован для другого содержимого.",
            code="mutation_id_reused",
        )
    blockers = submit_blockers(snapshot)
    if blockers:
        raise ScenarioValidationFailed(
            blockers[0]["message"], details={"violations": blockers}
        )
    if scenario is None:
        scenario = Scenario(
            round_id=round_id, participant_id=participant_id, revision=0
        )
        db.add(scenario)
    if scenario.payload_hash != digest:
        scenario.revision += 1
    scenario.steps = steps
    scenario.payload_hash = digest
    scenario.last_client_mutation_id = payload.client_mutation_id
    scenario.resource_snapshot = snapshot
    scenario.status = "submitted"
    scenario.submitted_at = scenario.updated_at = datetime.now(UTC)
    await db.flush()
    await record_event(
        db,
        actor_user_id=participant_id,
        round_id=round_id,
        scenario_id=scenario.id,
        event_type="scenario_submitted",
        request_id=request_id,
    )
    await db.commit()
    return scenario_out(scenario)
