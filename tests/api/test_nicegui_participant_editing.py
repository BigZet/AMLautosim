"""Repeated edits through live components after autosave must reach the backend."""

import asyncio
import importlib
import json

import httpx


def test_parameters_and_amount_remain_editable_after_autosave(
    api, player, active_round, tmp_path, monkeypatch
):
    from nicegui import app, ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.ui.nicegui.client import APIClient

    monkeypatch.setattr(Storage, "path", tmp_path)
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path))

    async def run():
        previews = []
        backend = httpx.ASGITransport(api.app)

        async def route(request):
            if request.url.path.endswith("/preview"):
                previews.append(json.loads(request.content))
            return await backend.handle_async_request(request)

        async with user_simulation() as user:
            front = importlib.import_module("src.aml_workshop_simulator.ui.nicegui.app")
            await front.api.close()
            front.api = APIClient(
                "http://test/api/v1", transport=httpx.MockTransport(route)
            )
            token = player["headers"]["X-Session-ID"]
            await user.open("/play/login")
            with user:
                app.storage.user["auth_play"] = {"session_id": token}
            await user.open("/play")
            await user.should_see("Входящий перевод", retries=40)
            cards = await front.api.request("GET", f"rounds/{active_round}/cards", session_id=token)
            assert any(c["code"] == "incoming_transfer" for c in cards)
            user.find(kind=ui.button, content="Входящий перевод").click()
            await asyncio.sleep(1.6)
            with user:
                sender = next(
                    e for e in user.find(ui.select).elements if e.label == "Отправитель"
                )
                sender.set_value("A")
                purpose = next(
                    e for e in user.find(ui.select).elements
                    if "unknown" in e.options and "shared_expense" in e.options
                )
                purpose.set_value("unknown")
            for value, total in [
                ("payment_service", "71000.01"),
                ("crypto_p2p", "72000.02"),
            ]:
                with user:
                    source = next(
                        e for e in user.find(ui.select).elements
                        if "crypto_p2p" in e.options
                    )
                    source.set_value(value)
                await asyncio.sleep(0.1)
                with user:
                    amount = next(
                        e for e in user.find(ui.number).elements if e.label == "Сумма"
                    )
                    amount.set_value(float(total))
                await asyncio.sleep(1.6)
                saved = await front.api.request(
                    "GET", f"rounds/{active_round}/scenario", session_id=token
                )
                assert saved["steps"][0]["action_details"]["incoming_kind"] == value
                assert saved["steps"][0]["amount"] == total
                assert (
                    previews[-1]["steps"][0]["action_details"]["incoming_kind"]
                    == value
                )
                assert previews[-1]["steps"][0]["amount"] == total
                assert source.value == value
                assert amount.value == float(total)
            incoming = next(c for c in cards if c["code"] == "incoming_transfer")
            minimum, maximum = float(incoming["min_amount"]), float(incoming["max_amount"])
            for invalid, expected in [(minimum - 1, minimum), (maximum + 1, maximum)]:
                with user:
                    amount.set_value(invalid)
                    assert not amount.validate()
                    amount.sanitize()  # Number's blur handler
                await asyncio.sleep(1.6)
                assert amount.value == expected
                saved = await front.api.request(
                    "GET", f"rounds/{active_round}/scenario", session_id=token
                )
                assert float(saved["steps"][0]["amount"]) == expected
            await user.open("/play")
            await user.should_see("Входящий перевод", retries=40)
            restored = next(
                e
                for e in user.find(ui.select).elements
                if "crypto_p2p" in e.options
            )
            assert restored.value == "crypto_p2p"
            before_profile = await front.api.request("GET", f"rounds/{active_round}/scenario", session_id=token)
            await user.open("/play/profile")
            await user.should_see("История операций", retries=40)
            await user.should_not_see(kind=ui.button, content="Входящий перевод")
            await user.open("/play")
            await user.should_see("Входящий перевод", retries=40)
            after_profile = await front.api.request("GET", f"rounds/{active_round}/scenario", session_id=token)
            assert after_profile["steps"] == before_profile["steps"]
            await front.api.close()

    asyncio.run(run())
