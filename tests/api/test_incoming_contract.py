"""New contract through the UI HTTP client, plus saved-round compatibility."""

import pytest

import asyncio
from uuid import uuid4

import httpx

from scripts.seed_database import seed
from src.aml_workshop_simulator.ui.nicegui.client import APIClient


def test_incoming_card_preview_save_submit_and_score(
    api, request_api, player, admin, active_round, chain
):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        path = f"rounds/{active_round}/scenario"
        try:
            cards = await client.request("GET", f"rounds/{active_round}/cards", session_id=player["headers"]["X-Session-ID"])
            assert {c["code"] for c in cards} == {
                "salary",
                "incoming_transfer",
                "card_transfer",
                "cash_withdrawal",
                "purchase",
            }
            incoming = next(c for c in cards if c["code"] == "incoming_transfer")
            assert [p["key"] for p in incoming["visible_params"]] == [
                "channel",
                "incoming_kind",
        "bank_country",
            ]
            assert (
                incoming["channels"] == ["bank"] and incoming["quota_category"] is None
            )
            steps = chain()
            for step in steps:
                if step["card"]["code"] == "incoming_transfer":
                    step["action_details"] = {
                        "incoming_kind": "crypto_p2p",
                    }
                    step["purpose_code"] = "unknown"
            sid = player["headers"]["X-Session-ID"]
            preview = await client.request(
                "POST", path + "/preview", session_id=sid, body={"steps": steps}
            )
            assert preview["can_submit"]
            assert preview["resources"]["limit_usage"]["cash"] == "10000.00"
            saved = await client.request(
                "PUT",
                path,
                session_id=sid,
                body={
                    "steps": steps,
                    "expected_revision": 0,
                    "client_mutation_id": str(uuid4()),
                },
            )
            assert saved["resources"] == preview["resources"]
            assert (await client.request("GET", path, session_id=sid))[
                "steps"
            ] == saved["steps"]
            assert all(
                s["context"]["channel"] == "bank"
                for s in saved["steps"]
                if s["card"]["code"] == "incoming_transfer"
            )
            submitted = await client.request(
                "POST",
                path + "/submit",
                session_id=sid,
                body={
                    "steps": saved["steps"],
                    "expected_revision": saved["revision"],
                    "client_mutation_id": str(uuid4()),
                },
            )
            assert submitted["status"] == "submitted"
            await client.request(
                "POST",
                f"admin/rounds/{active_round}/score?wait=true",
                session_id=admin["X-Session-ID"],
            )
            result = await client.request(
                "GET", f"rounds/{active_round}/result", session_id=sid
            )
            assert result is not None
        finally:
            await client.close()

    asyncio.run(run())


def test_explicit_seed_reset_replaces_game_but_keeps_accounts_and_sessions(
    api, request_api, player, admin, active_round, sql, chain, command
):
    request_api(
        "PUT", f"/rounds/{active_round}/scenario", player["headers"], command(chain())
    )
    users = sql("SELECT id, email FROM users ORDER BY id")
    sessions = sql("SELECT id FROM sessions ORDER BY id")
    before = sql("SELECT id, game_config FROM rounds")
    api.portal.call(seed)
    assert sql("SELECT id, game_config FROM rounds") == before
    api.portal.call(seed, True)
    current = request_api("GET", "/admin/rounds/current", admin)
    assert current["id"] != active_round
    assert current["status"] == "draft"
    assert current["game_config"]["schema_version"] == 10
    assert sql("SELECT id FROM scenarios") == []
    assert sql("SELECT id FROM scoring_results") == []
    assert sql("SELECT id, email FROM users ORDER BY id") == users
    assert sql("SELECT id FROM sessions ORDER BY id") == sessions
    request_api("GET", "/auth/session", player["headers"])


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
