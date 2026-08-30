"""Typed HTTP client for `/api/v1`.

Both Streamlit applications talk to FastAPI only through this class. Every
method mirrors one documented endpoint, returns the parsed envelope and turns
any failure — an error envelope, a non-JSON body or an unreachable API — into a
single `APIClientError` the UI can render.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

from src.aml_workshop_simulator.ui.shared.browser_meta import browser_headers

#: Per-method (connect, read) timeouts from docs/api.md section 16.
TIMEOUTS = {
    "GET": httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=5.0),
    "AUTH": httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=5.0),
    "WRITE": httpx.Timeout(connect=3.0, read=15.0, write=15.0, pool=5.0),
    "SCORE": httpx.Timeout(connect=3.0, read=30.0, write=30.0, pool=5.0),
}

API_UNREACHABLE = (
    "Сервис недоступен: не удалось связаться с сервером. "
    "Проверьте соединение и повторите попытку."
)


class APIClientError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        code: str = "error",
        details: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class SimulatorAPIClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url or os.getenv("API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self.api_prefix = "/api/v1"
        # The shared transport carries no session id: every protected call
        # passes X-Session-ID explicitly.
        self._client = httpx.Client(base_url=self.base_url, timeout=TIMEOUTS["GET"])

    # ---------------- plumbing ----------------
    def _url(self, path: str) -> str:
        if path.startswith("/"):
            return f"{self.api_prefix}{path}"
        return f"{self.api_prefix}/{path}"

    def _headers(
        self,
        session_id: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": request_id or str(uuid.uuid4()),
        }
        # The browser of the person in front of Streamlit, not this process.
        headers.update(browser_headers())
        if session_id:
            headers["X-Session-ID"] = session_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _handle_response(self, response: httpx.Response) -> Any:
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text}

        if response.is_error:
            msg = data.get("message") or data.get("detail") or "Ошибка API"
            code = data.get("code") or "api_error"
            details = data.get("details")
            raise APIClientError(
                message=msg,
                status_code=response.status_code,
                code=code,
                details=details,
            )
        return data

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        """One request, with transport failures mapped onto the error envelope."""
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise APIClientError(
                API_UNREACHABLE, status_code=503, code="service_unavailable"
            ) from error
        return self._handle_response(response)

    # ---------------- Auth ----------------
    def register(self, email: str, display_name: str, password: str) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url("/auth/register"),
            json={"email": email, "display_name": display_name, "password": password},
            headers=self._headers(),
            timeout=TIMEOUTS["AUTH"],
        )

    def login(
        self, email: str, password: str, audience: str = "play"
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url("/auth/login"),
            json={"email": email, "password": password, "audience": audience},
            headers=self._headers(),
            timeout=TIMEOUTS["AUTH"],
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET", self._url("/auth/session"), headers=self._headers(session_id)
        )

    def logout(self, session_id: str) -> None:
        self._send(
            "DELETE", self._url("/auth/session"), headers=self._headers(session_id)
        )

    # ---------------- Participant / Rounds ----------------
    def get_active_round(self) -> dict[str, Any] | None:
        return self._send("GET", self._url("/rounds/active"), headers=self._headers())

    def get_current_round(self) -> dict[str, Any] | None:
        """The round to display, including one that has not been started yet."""
        return self._send("GET", self._url("/rounds/current"), headers=self._headers())

    def get_my_rounds(
        self, session_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url("/rounds/mine"),
            params={"cursor": cursor} if cursor else None,
            headers=self._headers(session_id),
        )

    def get_round_cards(self, round_id: int) -> list[dict[str, Any]]:
        return self._send(
            "GET", self._url(f"/rounds/{round_id}/cards"), headers=self._headers()
        )

    def get_scenario(self, round_id: int, session_id: str) -> dict[str, Any] | None:
        return self._send(
            "GET",
            self._url(f"/rounds/{round_id}/scenario"),
            headers=self._headers(session_id),
        )

    def preview_scenario(
        self, round_id: int, steps: list[dict[str, Any]], session_id: str
    ) -> dict[str, Any]:
        """Server-side evaluation of an unsaved chain.

        Used after every change so the resources on screen are always the
        server's own numbers.
        """
        return self._send(
            "POST",
            self._url(f"/rounds/{round_id}/scenario/preview"),
            json={"steps": steps},
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def put_scenario(
        self,
        round_id: int,
        steps: list[dict[str, Any]],
        expected_revision: int,
        session_id: str,
        client_mutation_id: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Full draft replacement; a change appends a new saved version.

        `client_mutation_id` makes the call safe to retry: the same id with the
        same payload returns the original result instead of creating a second
        revision.
        """
        return self._send(
            "PUT",
            self._url(f"/rounds/{round_id}/scenario"),
            json={
                "expected_revision": expected_revision,
                "client_mutation_id": client_mutation_id,
                "steps": steps,
                "label": label,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def list_scenario_versions(self, round_id: int, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/rounds/{round_id}/scenario/versions"),
            headers=self._headers(session_id),
        )

    def get_scenario_version(
        self, round_id: int, revision: int, session_id: str
    ) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/rounds/{round_id}/scenario/versions/{revision}"),
            headers=self._headers(session_id),
        )

    def restore_scenario_version(
        self,
        round_id: int,
        revision: int,
        expected_revision: int,
        session_id: str,
        client_mutation_id: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/rounds/{round_id}/scenario/versions/{revision}/restore"),
            json={
                "expected_revision": expected_revision,
                "client_mutation_id": client_mutation_id,
                "label": label,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def submit_scenario(
        self, round_id: int, expected_revision: int, session_id: str
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/rounds/{round_id}/scenario/submit"),
            json={"expected_revision": expected_revision},
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def get_result(self, round_id: int, session_id: str) -> dict[str, Any] | None:
        return self._send(
            "GET",
            self._url(f"/rounds/{round_id}/result"),
            headers=self._headers(session_id),
        )

    def get_leaderboard(
        self,
        round_id: int,
        session_id: str | None = None,
        reveal: bool = False,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Masked by default; `reveal` is the explicit request for nicknames."""
        params: dict[str, str] = {}
        if reveal:
            params["reveal"] = "true"
        if cursor:
            params["cursor"] = cursor
        return self._send(
            "GET",
            self._url(f"/rounds/{round_id}/leaderboard"),
            params=params or None,
            headers=self._headers(session_id),
        )

    # ---------------- Admin: catalog and rounds ----------------
    def admin_default_game_config(self, session_id: str) -> dict[str, Any]:
        return self._send("GET", self._url("/admin/game-config/default"), headers=self._headers(session_id))

    def admin_get_action_cards(self, session_id: str) -> list[dict[str, Any]]:
        return self._send(
            "GET", self._url("/admin/action-cards"), headers=self._headers(session_id)
        )

    def admin_list_rounds(self, session_id: str) -> list[dict[str, Any]]:
        return self._send(
            "GET", self._url("/admin/rounds"), headers=self._headers(session_id)
        )

    def admin_get_round(self, round_id: int, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}"),
            headers=self._headers(session_id),
        )

    def admin_create_round(
        self,
        title: str,
        game_config: dict[str, Any] | None,
        session_id: str,
        preset_id: int | None = None,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url("/admin/rounds"),
            json={
                "title": title,
                "game_config": game_config,
                "preset_id": preset_id,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_update_round(
        self,
        round_id: int,
        expected_config_revision: int,
        title: str | None,
        game_config: dict[str, Any] | None,
        session_id: str,
    ) -> dict[str, Any]:
        return self._send(
            "PUT",
            self._url(f"/admin/rounds/{round_id}"),
            json={
                "expected_config_revision": expected_config_revision,
                "title": title,
                "game_config": game_config,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_start_round(
        self, round_id: int, session_id: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/admin/rounds/{round_id}/start"),
            headers=self._headers(session_id, idempotency_key=idempotency_key),
            timeout=TIMEOUTS["WRITE"],
        )

    #: Kept so older callers and the documented endpoint name keep working.
    def admin_activate_round(
        self, round_id: int, session_id: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/admin/rounds/{round_id}/activate"),
            headers=self._headers(session_id, idempotency_key=idempotency_key),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_stop_round(
        self,
        round_id: int,
        session_id: str,
        confirm: bool = True,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/admin/rounds/{round_id}/stop"),
            json={"confirm": confirm, "reason": reason},
            headers=self._headers(session_id, idempotency_key=idempotency_key),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_restart_round(
        self,
        round_id: int,
        session_id: str,
        confirm: bool = True,
        title: str | None = None,
        reason: str | None = None,
        activate: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/admin/rounds/{round_id}/restart"),
            json={
                "confirm": confirm,
                "title": title,
                "reason": reason,
                "activate": activate,
            },
            headers=self._headers(session_id, idempotency_key=idempotency_key),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_get_scoring_plan(self, round_id: int, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/scoring-plan"),
            headers=self._headers(session_id),
        )

    def admin_trigger_scoring(
        self, round_id: int, session_id: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url(f"/admin/rounds/{round_id}/score"),
            headers=self._headers(session_id, idempotency_key=idempotency_key),
            timeout=TIMEOUTS["SCORE"],
        )

    def admin_get_stats(self, round_id: int, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/stats"),
            headers=self._headers(session_id),
        )

    # ---------------- Admin: presets ----------------
    def admin_list_presets(self, session_id: str) -> list[dict[str, Any]]:
        return self._send(
            "GET", self._url("/admin/round-presets"), headers=self._headers(session_id)
        )

    def admin_get_preset(self, preset_id: int, session_id: str) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/round-presets/{preset_id}"),
            headers=self._headers(session_id),
        )

    def admin_create_preset(
        self,
        name: str,
        description: str | None,
        game_config: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            self._url("/admin/round-presets"),
            json={
                "name": name,
                "description": description,
                "game_config": game_config,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_update_preset(
        self,
        preset_id: int,
        expected_revision: int,
        session_id: str,
        name: str | None = None,
        description: str | None = None,
        game_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send(
            "PUT",
            self._url(f"/admin/round-presets/{preset_id}"),
            json={
                "expected_revision": expected_revision,
                "name": name,
                "description": description,
                "game_config": game_config,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_delete_preset(self, preset_id: int, session_id: str) -> None:
        self._send(
            "DELETE",
            self._url(f"/admin/round-presets/{preset_id}"),
            params={"confirm": "true"},
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    # ---------------- Admin: participants ----------------
    def admin_list_participants(
        self,
        round_id: int,
        query: str | None,
        access: str,
        status: str | None,
        session_id: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"access": access, "limit": str(limit)}
        if query:
            params["query"] = query
        if status and status != "all":
            params["scenario_status"] = status
        if cursor:
            params["cursor"] = cursor
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/participants"),
            params=params,
            headers=self._headers(session_id),
        )

    def admin_get_participant_detail(
        self, round_id: int, participant_id: int, session_id: str
    ) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/participants/{participant_id}"),
            headers=self._headers(session_id),
        )

    def admin_get_participant_version(
        self, round_id: int, participant_id: int, revision: int, session_id: str
    ) -> dict[str, Any]:
        """One saved draft version with every step parameter resolved."""
        return self._send(
            "GET",
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}"
                f"/scenario-versions/{revision}"
            ),
            headers=self._headers(session_id),
        )

    def admin_update_access(
        self,
        round_id: int,
        participant_id: int,
        blocked: bool,
        reason: str,
        expected_access_revision: int,
        session_id: str,
    ) -> dict[str, Any]:
        return self._send(
            "PUT",
            self._url(f"/admin/rounds/{round_id}/participants/{participant_id}/access"),
            json={
                "blocked": blocked,
                "reason": reason,
                "expected_access_revision": expected_access_revision,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    # ---------------- Admin: leaderboard and audit ----------------
    def admin_adjust_leaderboard(
        self,
        round_id: int,
        participant_id: int,
        expected_revision: int,
        reason: str,
        risk_override: str | None,
        resource_override: str | None,
        game_override: str | None,
        session_id: str,
    ) -> dict[str, Any]:
        return self._send(
            "PUT",
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}"
                "/leaderboard-adjustment"
            ),
            json={
                "expected_revision": expected_revision,
                "reason": reason,
                "risk_score_override": risk_override,
                "resource_score_override": resource_override,
                "game_score_override": game_override,
            },
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_clear_leaderboard_adjustment(
        self,
        round_id: int,
        participant_id: int,
        session_id: str,
        expected_revision: int,
    ) -> None:
        self._send(
            "DELETE",
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}"
                "/leaderboard-adjustment"
            ),
            params={"expected_revision": expected_revision},
            headers=self._headers(session_id),
            timeout=TIMEOUTS["WRITE"],
        )

    def admin_get_leaderboard(
        self, round_id: int, session_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/leaderboard"),
            params={"cursor": cursor} if cursor else None,
            headers=self._headers(session_id),
        )

    def admin_get_audit_events(
        self, round_id: int, session_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._send(
            "GET",
            self._url(f"/admin/rounds/{round_id}/audit-events"),
            params={"cursor": cursor} if cursor else None,
            headers=self._headers(session_id),
        )
