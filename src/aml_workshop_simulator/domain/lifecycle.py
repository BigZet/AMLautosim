"""Rules for a single-use round and one final submission per participant."""

from src.aml_workshop_simulator.core.errors import Conflict


def require_round_status(status: str, expected: str) -> None:
    if status != expected:
        raise Conflict(
            "Действие недоступно в текущем состоянии раунда.",
            code="round_locked",
            details={"round_status": status},
        )


def require_editable(round_status: str, scenario_status: str | None) -> None:
    require_round_status(round_status, "active")
    if scenario_status is not None and scenario_status != "editing":
        raise Conflict(
            "Сценарий уже отправлен. Повторная попытка недоступна.",
            code="scenario_submitted",
        )


def require_revision(current: int, expected: int) -> None:
    if current != expected:
        raise Conflict(
            "Сценарий изменён в другом окне. Загрузите актуальное состояние.",
            code="scenario_revision_conflict",
            details={"current_revision": current},
        )
