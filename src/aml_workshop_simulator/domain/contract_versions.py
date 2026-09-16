"""Snapshot versions are distinct from scoring and resource-rule versions.

Released v8 snapshots are playable; earlier stage snapshots remain read-only.
Creation can be disabled independently of servicing saved released rounds.
"""

from src.aml_workshop_simulator.core.errors import Conflict, ValidationFailed

LEGACY_CONTRACT_VERSION = 7
EXPANDED_CONTRACT_VERSION = 8


def contract_version(config: dict | None) -> int:
    # The pure legacy engine historically accepts partial configs without a
    # version. Persisted DTOs still validate complete snapshots separately.
    version = (config or {}).get("schema_version", LEGACY_CONTRACT_VERSION)
    if type(version) is not int or version not in (
        LEGACY_CONTRACT_VERSION,
        EXPANDED_CONTRACT_VERSION,
        9,
    ):
        raise ValidationFailed(
            "Версия контракта раунда не поддерживается.",
            code="round_contract_unsupported",
            details={"schema_version": version},
        )
    return version


def is_playable_contract(config: dict | None) -> bool:
    return contract_version(config) == LEGACY_CONTRACT_VERSION or (
        (config or {}).get("behavior", {}).get("release") == "expanded-game-v1"
    )


def require_playable_contract(config: dict | None) -> None:
    if not is_playable_contract(config):
        raise Conflict(
            "Расширенный контракт раунда ещё не готов к запуску и расчёту.",
            code="round_contract_not_ready",
            details={"schema_version": EXPANDED_CONTRACT_VERSION},
        )


def require_legacy_contract(config):
    if contract_version(config) != LEGACY_CONTRACT_VERSION:
        raise Conflict(
            "Контракт v8 требует расширенный движок.", code="round_contract_not_ready"
        )


def require_new_round_allowed(config):
    if contract_version(config) == 9:
        raise Conflict("Контракт v9 ожидает согласования рубрики и проверки новой модели.", code="round_contract_not_ready")
    require_playable_contract(config)
    if contract_version(config) == EXPANDED_CONTRACT_VERSION:
        from src.aml_workshop_simulator.core.config import settings

        if not settings.EXPANDED_ROUNDS_ENABLED:
            raise Conflict(
                "Создание новых расширенных раундов отключено.",
                code="expanded_rounds_disabled",
            )
