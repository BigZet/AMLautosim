from __future__ import annotations

import os
from typing import Any, Optional
import httpx


class APIClientError(Exception):
    def __init__(
            self,
            message: str,
            status_code: int = 500,
            code: str = "error",
            details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class SimulatorAPIClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url or os.getenv(
                "API_URL",
                "http://127.0.0.1:8000")).rstrip("/")
        self.api_prefix = "/api/v1"
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def _url(self, path: str) -> str:
        if path.startswith("/"):
            return f"{self.api_prefix}{path}"
        return f"{self.api_prefix}/{path}"

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["X-Session-ID"] = session_id
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
                details=details)
        return data

    # ---------------- Auth ----------------
    def register(self, email: str, display_name: str,
                 password: str) -> dict[str, Any]:
        resp = self._client.post(
            self._url("/auth/register"),
            json={
                "email": email,
                "display_name": display_name,
                "password": password},
        )
        return self._handle_response(resp)

    def login(self, email: str, password: str,
              audience: str = "play") -> dict[str, Any]:
        resp = self._client.post(
            self._url("/auth/login"),
            json={"email": email, "password": password, "audience": audience},
        )
        return self._handle_response(resp)

    def get_session(self, session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url("/auth/session"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def logout(self, session_id: str) -> None:
        resp = self._client.delete(
            self._url("/auth/session"),
            headers=self._headers(session_id))
        self._handle_response(resp)

    # ---------------- Participant / Rounds ----------------
    def get_active_round(self) -> dict[str, Any] | None:
        resp = self._client.get(self._url("/rounds/active"))
        return self._handle_response(resp)

    def get_my_rounds(self, session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url("/rounds/mine"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def get_round_cards(self, round_id: int) -> list[dict[str, Any]]:
        resp = self._client.get(self._url(f"/rounds/{round_id}/cards"))
        return self._handle_response(resp)

    def get_scenario(self, round_id: int,
                     session_id: str) -> dict[str, Any] | None:
        resp = self._client.get(
            self._url(
                f"/rounds/{round_id}/scenario"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def put_scenario(self,
                     round_id: int,
                     steps: list[dict[str,
                                      Any]],
                     expected_revision: int,
                     session_id: str) -> dict[str,
                                              Any]:
        resp = self._client.put(
            self._url(f"/rounds/{round_id}/scenario"),
            json={"expected_revision": expected_revision, "steps": steps},
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def submit_scenario(self,
                        round_id: int,
                        expected_revision: int,
                        session_id: str) -> dict[str,
                                                 Any]:
        resp = self._client.post(
            self._url(f"/rounds/{round_id}/scenario/submit"),
            json={"expected_revision": expected_revision},
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def get_result(self, round_id: int,
                   session_id: str) -> dict[str, Any] | None:
        resp = self._client.get(
            self._url(
                f"/rounds/{round_id}/result"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def get_leaderboard(self, round_id: int, session_id: str |
                        None = None) -> dict[str, Any]:
        resp = self._client.get(
            self._url(
                f"/rounds/{round_id}/leaderboard"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    # ---------------- Admin ----------------
    def admin_get_action_cards(self, session_id: str) -> list[dict[str, Any]]:
        resp = self._client.get(
            self._url("/admin/action-cards"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_list_rounds(self, session_id: str) -> list[dict[str, Any]]:
        resp = self._client.get(
            self._url("/admin/rounds"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_get_round(self, round_id: int,
                        session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url(
                f"/admin/rounds/{round_id}"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_create_round(self,
                           title: str,
                           game_config: dict[str,
                                             Any],
                           session_id: str) -> dict[str,
                                                    Any]:
        resp = self._client.post(
            self._url("/admin/rounds"),
            json={"title": title, "game_config": game_config},
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def admin_update_round(self,
                           round_id: int,
                           expected_config_revision: int,
                           title: str | None,
                           game_config: dict[str,
                                             Any] | None,
                           session_id: str) -> dict[str,
                                                    Any]:
        resp = self._client.put(
            self._url(
                f"/admin/rounds/{round_id}"),
            json={
                "expected_config_revision": expected_config_revision,
                "title": title,
                "game_config": game_config},
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def admin_activate_round(
            self, round_id: int, session_id: str) -> dict[str, Any]:
        resp = self._client.post(
            self._url(
                f"/admin/rounds/{round_id}/activate"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_trigger_scoring(
            self, round_id: int, session_id: str) -> dict[str, Any]:
        resp = self._client.post(
            self._url(
                f"/admin/rounds/{round_id}/score"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_get_stats(self, round_id: int,
                        session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url(
                f"/admin/rounds/{round_id}/stats"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_list_participants(self,
                                round_id: int,
                                query: str | None,
                                access: str,
                                status: str | None,
                                session_id: str) -> list[dict[str,
                                                              Any]]:
        params = {"access": access}
        if query:
            params["query"] = query
        if status and status != "all":
            params["scenario_status"] = status
        resp = self._client.get(
            self._url(
                f"/admin/rounds/{round_id}/participants"),
            params=params,
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_get_participant_detail(
            self, round_id: int, participant_id: int, session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}"),
            headers=self._headers(session_id))
        return self._handle_response(resp)

    def admin_update_access(self,
                            round_id: int,
                            participant_id: int,
                            blocked: bool,
                            reason: str,
                            expected_access_revision: int,
                            session_id: str) -> dict[str,
                                                     Any]:
        resp = self._client.put(
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}/access"),
            json={
                "blocked": blocked,
                "reason": reason,
                "expected_access_revision": expected_access_revision},
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def admin_adjust_leaderboard(self,
                                 round_id: int,
                                 participant_id: int,
                                 expected_revision: int,
                                 reason: str,
                                 risk_override: str | None,
                                 resource_override: str | None,
                                 game_override: str | None,
                                 session_id: str) -> dict[str,
                                                          Any]:
        resp = self._client.put(
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment"),
            json={
                "expected_revision": expected_revision,
                "reason": reason,
                "risk_score_override": risk_override,
                "resource_score_override": resource_override,
                "game_score_override": game_override,
            },
            headers=self._headers(session_id),
        )
        return self._handle_response(resp)

    def admin_clear_leaderboard_adjustment(
            self,
            round_id: int,
            participant_id: int,
            session_id: str) -> None:
        resp = self._client.delete(
            self._url(
                f"/admin/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment"),
            headers=self._headers(session_id))
        self._handle_response(resp)

    def admin_get_audit_events(
            self, round_id: int, session_id: str) -> dict[str, Any]:
        resp = self._client.get(
            self._url(
                f"/admin/rounds/{round_id}/audit-events"),
            headers=self._headers(session_id))
        return self._handle_response(resp)
