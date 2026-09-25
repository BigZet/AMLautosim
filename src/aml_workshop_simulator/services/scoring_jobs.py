"""PostgreSQL queue with fenced leases and atomic result publication."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import logging
from threading import local
import time
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import load_only

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.errors import ApplicationError, Conflict, NotFound
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_jobs import ScoringJob
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.schemas.admin import ScoringJobOut
from src.aml_workshop_simulator.services import scoring_run
from src.aml_workshop_simulator.services.audit import record_event

logger = logging.getLogger(__name__)
_thread = local()


def projection(job):
    return ScoringJobOut(
        job_id=job.id,
        round_id=job.round_id,
        original_round_id=job.original_round_id,
        state=job.state,
        done=job.done,
        total=job.total,
        attempt=job.attempt,
        error=job.error,
        summary=job.summary,
    )


async def read(db, job_id):
    job = (
        await db.execute(
            select(ScoringJob)
            .options(
                load_only(
                    ScoringJob.id,
                    ScoringJob.round_id,
                    ScoringJob.original_round_id,
                    ScoringJob.state,
                    ScoringJob.done,
                    ScoringJob.total,
                    ScoringJob.attempt,
                    ScoringJob.error,
                    ScoringJob.summary,
                    raiseload=True,
                )
            )
            .where(ScoringJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFound("Задание расчёта не найдено.", code="scoring_job_not_found")
    return projection(job)


async def freeze_snapshot(db, row):
    scenarios = (
        (
            await db.execute(
                select(Scenario)
                .where(
                    Scenario.round_id == row.id,
                    Scenario.status == "submitted",
                )
                .order_by(Scenario.id)
                .limit(settings.SCORING_MAX_SCENARIOS + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(scenarios) > settings.SCORING_MAX_SCENARIOS:
        raise Conflict(
            "Превышен настроенный предел сценариев расчёта.",
            code="scoring_capacity_limit",
        )
    value = {
        "config_revision": row.config_revision,
        "config": deepcopy(row.game_config),
        "scenarios": [
            {"id": s.id, "revision": s.revision, "steps": deepcopy(s.steps)}
            for s in scenarios
        ],
    }
    if (
        len(json.dumps(value, ensure_ascii=False).encode())
        > settings.SCORING_MAX_SNAPSHOT_BYTES
    ):
        raise Conflict(
            "Превышен настроенный объём задания расчёта.", code="scoring_capacity_limit"
        )
    return value


async def enqueue(db, round_id, actor_id, request_id):
    # A crash after this commit cannot reopen admission or resurrect drafts.
    await scoring_run.close_admission(db, round_id, actor_id, request_id)
    row = await get_round(db, round_id, lock="update")
    existing = (
        await db.execute(
            select(ScoringJob)
            .where(
                ScoringJob.round_id == round_id,
                ScoringJob.state.in_(["queued", "running", "completed"]),
            )
            .order_by(ScoringJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        result = projection(existing)
        await db.commit()
        return result
    now = (await db.execute(select(func.now()))).scalar_one()
    completed = row.status == "completed"
    snapshot = (
        {
            "config_revision": row.config_revision,
            "config": deepcopy(row.game_config),
            "scenarios": [],
        }
        if completed
        else await freeze_snapshot(db, row)
    )
    total = (
        row.scoring_summary["scored_count"] if completed else len(snapshot["scenarios"])
    )
    job = ScoringJob(
        id=uuid4(),
        round_id=round_id,
        original_round_id=round_id,
        actor_id=actor_id,
        request_id=request_id,
        state="completed" if completed else "queued",
        done=total if completed else 0,
        total=total,
        attempt=0,
        snapshot=snapshot,
        summary=scoring_run._summary(row).model_dump(mode="json")
        if completed
        else None,
        created_at=now,
        finished_at=now if completed else None,
    )
    db.add(job)
    if not completed:
        row.status = "scoring"
        row.scoring_started_at = now
        row.scoring_error = None
        await record_event(
            db,
            actor_user_id=actor_id,
            round_id=round_id,
            event_type="scoring_queued",
            request_id=request_id,
            metadata={"job_id": str(job.id), "total": total},
        )
    await db.commit()
    return projection(job)


async def claim(sessions):
    async with sessions() as db:
        job = (
            await db.execute(
                select(ScoringJob)
                .where(
                    or_(
                        ScoringJob.state == "queued",
                        and_(
                            ScoringJob.state == "running",
                            ScoringJob.lease_until <= func.now(),
                        ),
                    )
                )
                .order_by(ScoringJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        now = (await db.execute(select(func.now()))).scalar_one()
        if job.round_id is None:
            job.state, job.finished_at = "cancelled", now
            await db.commit()
            return None
        job.state = "running"
        job.owner = uuid4()
        job.attempt += 1
        job.done = 0
        job.started_at = now
        job.lease_until = now + timedelta(seconds=settings.SCORING_LEASE_SECONDS)
        job.error = None
        await db.commit()
        return {
            "id": job.id,
            "owner": job.owner,
            "round_id": job.round_id,
            "snapshot": deepcopy(job.snapshot),
        }


def _owned(claimed):
    return (
        ScoringJob.id == claimed["id"],
        ScoringJob.owner == claimed["owner"],
        ScoringJob.state == "running",
        ScoringJob.lease_until > func.now(),
    )


async def progress(sessions, claimed, done=None):
    async with sessions() as db:
        values = {
            "lease_until": func.now()
            + timedelta(seconds=settings.SCORING_LEASE_SECONDS)
        }
        if done is not None:
            values["done"] = done
        result = await db.execute(
            update(ScoringJob).where(*_owned(claimed)).values(**values)
        )
        await db.commit()
        return result.rowcount == 1


def initialize_calculator(config):
    from src.aml_workshop_simulator.services.game_classifier import (
        GameClassifier,
        get_pinned_game_classifier,
    )
    from src.aml_workshop_simulator.services.model_scoring import ModelScorer
    from src.aml_workshop_simulator.services.scenario_service import (
        load_round_card_specs,
        round_policy,
    )

    config = deepcopy(config)
    # A model instance is owned by exactly one executor thread, including legacy.
    scorer = (
        GameClassifier(get_pinned_game_classifier(config).package)
        if config["schema_version"] == 10
        else ModelScorer()
    )
    scorer.check_config(config, require_pin=True)
    row = SimpleNamespace(game_config=config)
    specs = load_round_card_specs(row)
    _thread.calculator = (specs, config, round_policy(row, specs), scorer)


def calculate_step(steps):
    from src.aml_workshop_simulator.services.scoring_service import _evaluate

    return _evaluate(deepcopy(steps), *_thread.calculator)


async def publish(sessions, claimed, outputs, duration_ms):
    async with sessions() as db:
        # Consistent lock order with enqueue/restart: round, then job.
        row = (
            await db.execute(
                select(Round).where(Round.id == claimed["round_id"]).with_for_update()
            )
        ).scalar_one_or_none()
        job = (
            await db.execute(
                select(ScoringJob).where(*_owned(claimed)).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return False
        if row is None or row.status != "scoring":
            job.state = "cancelled"
            job.owner = job.lease_until = None
            job.finished_at = (await db.execute(select(func.now()))).scalar_one()
            await db.commit()
            return False
        snapshot = claimed["snapshot"]
        actual = (
            await db.execute(
                select(Scenario.id, Scenario.revision, Scenario.status)
                .where(Scenario.round_id == row.id)
                .order_by(Scenario.id)
            )
        ).all()
        expected = [
            (s["id"], s["revision"], "submitted") for s in snapshot["scenarios"]
        ]
        if (
            row.config_revision != snapshot["config_revision"]
            or row.game_config != snapshot["config"]
            or [tuple(r) for r in actual] != expected
        ):
            raise Conflict(
                "Данные раунда изменились после постановки расчёта.",
                code="scoring_snapshot_changed",
            )
        # Existing publication writer remains inside this transaction. Any error
        # (including after flush/audit) rolls back every result and scenario update.
        await scoring_run.score_round(
            db,
            row,
            job.actor_id,
            job.request_id,
            prepared=outputs,
            duration_ms=duration_ms,
        )
        job.state, job.done = "completed", job.total
        job.summary = scoring_run._summary(row).model_dump(mode="json")
        job.owner = job.lease_until = None
        job.finished_at = row.completed_at
        await db.commit()
        return True


async def fail(sessions, claimed, exc):
    error = (
        exc
        if isinstance(exc, ApplicationError)
        else ApplicationError(
            "Ошибка скоринга. Приём сценариев закрыт; организатор может повторить расчёт.",
            code="scoring_failed",
            status_code=500,
        )
    )
    async with sessions() as db:
        row = (
            await db.execute(
                select(Round).where(Round.id == claimed["round_id"]).with_for_update()
            )
        ).scalar_one_or_none()
        job = (
            await db.execute(
                select(ScoringJob).where(*_owned(claimed)).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return
        now = (await db.execute(select(func.now()))).scalar_one()
        job.state = "failed" if row is not None else "cancelled"
        job.error = {
            "code": error.code,
            "message": error.message,
            "request_id": job.request_id,
            "status_code": error.status_code,
        }
        job.finished_at, job.owner, job.lease_until = now, None, None
        if row is not None:
            row.status = "closed"
            row.scoring_error = {
                k: v for k, v in job.error.items() if k != "status_code"
            }
            await record_event(
                db,
                actor_user_id=job.actor_id,
                round_id=row.id,
                event_type="scoring_failed",
                request_id=job.request_id,
                metadata={
                    "job_id": str(job.id),
                    "attempt": job.attempt,
                    "error_type": type(exc).__name__,
                    **row.scoring_error,
                },
            )
        await db.commit()


async def execute_claimed(sessions, claimed):
    lost = asyncio.Event()

    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(settings.SCORING_LEASE_SECONDS / 3)
                if not await progress(sessions, claimed):
                    lost.set()
                    return
        except Exception:
            logger.exception("Scoring heartbeat failed: job_id=%s", claimed["id"])
            lost.set()

    keeper = asyncio.create_task(heartbeat())
    started = time.perf_counter()
    try:
        outputs = []
        scenarios = claimed["snapshot"]["scenarios"]
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(
            settings.SCORING_THREADS,
            initializer=initialize_calculator,
            initargs=(claimed["snapshot"]["config"],),
        ) as pool:
            # At most SCORING_THREADS computations are queued; no unbounded gather.
            for offset in range(0, len(scenarios), settings.SCORING_THREADS):
                batch = scenarios[offset : offset + settings.SCORING_THREADS]
                futures = [
                    loop.run_in_executor(pool, calculate_step, s["steps"])
                    for s in batch
                ]
                results = await asyncio.gather(*futures, return_exceptions=True)
                for item, result in zip(batch, results, strict=True):
                    if isinstance(result, BaseException):
                        raise result
                    snapshot, values = result
                    outputs.append(
                        {"id": item["id"], "snapshot": snapshot, "values": values}
                    )
                    if lost.is_set() or not await progress(
                        sessions, claimed, len(outputs)
                    ):
                        return
        if not lost.is_set():
            await publish(
                sessions, claimed, outputs, int((time.perf_counter() - started) * 1000)
            )
    except Exception as exc:
        if not isinstance(exc, ApplicationError):
            logger.exception("Scoring job failed: job_id=%s", claimed["id"])
        await fail(sessions, claimed, exc)
    finally:
        keeper.cancel()
        try:
            await keeper
        except asyncio.CancelledError:
            pass


async def run_one(sessions):
    claimed = await claim(sessions)
    if claimed is None:
        return False
    await execute_claimed(sessions, claimed)
    return True


async def worker_loop(sessions, stop, poll_seconds=0.5):
    while not stop.is_set():
        if not await run_one(sessions):
            try:
                await asyncio.wait_for(stop.wait(), poll_seconds)
            except TimeoutError:
                pass
