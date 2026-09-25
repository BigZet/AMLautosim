"""Exercise actual NiceGUI callbacks in-process, without a browser driver."""

import asyncio
import importlib
from uuid import uuid4

import httpx
import pytest


def test_registration_login_and_full_workshop(
    api, tmp_path, monkeypatch, chain, request_api, round_id
):
    from nicegui import app, ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.ui.nicegui.client import APIClient

    monkeypatch.setattr(Storage, "path", tmp_path)
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path))

    async def run():
        async with user_simulation() as user:
            front = importlib.import_module("src.aml_workshop_simulator.ui.nicegui.app")
            await front.api.close()
            front.api = APIClient(
                "http://test/api/v1", transport=httpx.ASGITransport(api.app)
            )
            await user.open("/play/register")
            user.find("Имя участника").type("Тест формы")
            email = f"{uuid4().hex}@example.com"
            user.find("Email").type(email)
            user.find("Пароль").type("participant123")
            user.find("Повторите пароль").type("different")
            user.find("Зарегистрироваться").click()
            await asyncio.sleep(0.1)
            with user:
                confirmation = next(
                    e
                    for e in user.find(ui.input).elements
                    if e.label == "Повторите пароль"
                )
                assert confirmation.props["error"]
                confirmation.set_value("participant123")
            user.find("Зарегистрироваться").click()
            await user.should_see("Ожидаем начала игры", retries=40)
            with user:
                assert (
                    app.storage.user["auth_play"]["user"]["display_name"]
                    == "Тест формы"
                )
                assert "session_id" not in app.storage.browser
            await user.open("/play")
            await user.should_see("Ожидаем начала игры", retries=40)
            logout = user.find(ui.button)
            logout.elements = {
                b for b in logout.elements if b.props.get("icon") == "logout"
            }
            assert len(logout.elements) == 1
            logout.click()
            await user.should_see("Войти", retries=30)
            with user:
                assert "auth_play" not in app.storage.user
            user.find("Email").type("absent@example.com")
            user.find("Пароль").type("invalid12345")
            user.find("Войти").click()
            await user.should_see("Неверный email или пароль.", retries=40)
            with user:
                password = next(
                    e for e in user.find(ui.input).elements if e.label == "Пароль"
                )
                assert password.value == ""
            await user.open("/admin/login")
            user.find("Email").type("admin@example.com")
            user.find("Пароль").type("admin12345")
            user.find("Войти").click()
            await user.should_see("Сохранить настройки", retries=40)
            with user:
                name = next(
                    e
                    for e in user.find(ui.input).elements
                    if e.label == "Название игры"
                )
                name.set_value("Игра NiceGUI")
            from nicegui.nicegui import _on_handshake

            client = user.client
            socket_id, document_id = next(iter(client._socket_to_document_id.items()))
            with user:
                client.handle_disconnect(socket_id)
                await _on_handshake(
                    f"test-{uuid4()}",
                    {
                        "client_id": client.id,
                        "tab_id": user.tab_id,
                        "document_id": document_id,
                    },
                )
            await asyncio.sleep(0.2)
            assert name.value == "Игра NiceGUI"
            await user.open("/admin")
            await user.should_see("Сохранить настройки", retries=40)
            with user:
                name = next(
                    e
                    for e in user.find(ui.input).elements
                    if e.label == "Название игры"
                )
                assert name.value == "Игра NiceGUI"
                assert app.storage.user["workspace_admin"]
                admin_token = app.storage.user["auth_admin"]["session_id"]
            current = await front.api.request(
                "GET", "admin/rounds/current", session_id=admin_token
            )
            config = dict(current["game_config"])
            config.pop("risk_model", None)
            config.pop("config_version", None)
            config.pop("card_snapshots", None)
            await front.api.request(
                "PUT",
                f"admin/rounds/{current['id']}",
                session_id=admin_token,
                body={
                    "title": "Из другого окна",
                    "game_config": config,
                    "expected_config_revision": current["config_revision"],
                },
            )
            await user.open("/admin")
            await user.should_see("Настройки изменены в другом окне", retries=40)
            with user:
                name = next(
                    e
                    for e in user.find(ui.input).elements
                    if e.label == "Название игры"
                )
                assert name.value == "Игра NiceGUI"
            user.find("Загрузить актуальные").click()
            await user.should_see("Подтвердить")
            user.find(kind=ui.button, content="Подтвердить").click()
            await asyncio.sleep(0.3)
            with user:
                name = next(
                    e
                    for e in user.find(ui.input).elements
                    if e.label == "Название игры"
                )
                assert name.value == "Из другого окна"
                name.set_value("Игра NiceGUI")
            user.find("Сохранить настройки").click()
            await asyncio.sleep(0.5)
            with user:
                assert not app.storage.user["workspace_admin"]
            user.find("Начать игру").click()
            await user.should_see("Подтвердить")
            user.find("Подтвердить").click()
            await user.should_see(
                "Настройки зафиксированы до следующей игры.", retries=40
            )
            await user.open("/play/login")
            user.find("Email").type(email)
            user.find("Пароль").type("participant123")
            user.find("Войти").click()
            await user.should_see("Входящий перевод", retries=40)
            for step in chain():
                user.find(
                    kind=ui.button, content={"salary":"Зарплата", "incoming_transfer":"Входящий перевод", "card_transfer":"Перевод по карте", "cash_withdrawal":"Наличные", "purchase":"Покупка"}[step["card"]["code"]]
                ).click()
                with user:
                    amount = max(
                        (
                            e
                            for e in user.find(ui.number).elements
                            if e.label == "Сумма"
                        ),
                        key=lambda e: e.id,
                    )
                    amount.set_value(float(step["amount"]))
                    for key, label in (
                        ("sender_id", "Отправитель"),
                        ("recipient_id", "Получатель"),
                    ):
                        if step.get(key):
                            selector = max(
                                (
                                    e
                                    for e in user.find(ui.select).elements
                                    if e.label == label
                                ),
                                key=lambda e: e.id,
                            )
                            selector.set_value(step[key])
            await asyncio.sleep(1.8)
            await user.should_see("Сохранено", retries=40)
            user.find(kind=ui.expansion, content="Условия отправки").click()
            await user.should_see("Лимиты и цель")
            await user.should_see("Всё готово к отправке")
            user.find("Отправить сценарий").click()
            await user.should_see("Отправить сценарий окончательно?")
            user.find("confirm-submit").click()
            await user.should_see("Сценарий принят", retries=40)
            await user.open("/admin")
            await user.should_see("Запустить скоринг", retries=40)
            user.find("Запустить скоринг").click()
            await user.should_see("Подтвердить")
            user.find("Подтвердить").click()
            await user.should_see("Игра завершена", retries=40)
            await user.open("/play")
            await user.should_see("Ваш результат", retries=40)
            user.find(kind=ui.tab, content="Операции").click()
            await user.should_see("Ваши операции")
            await user.should_see("1. Получить входящий перевод")
            await user.should_not_see("10. Перевести по карте")
            user.find(kind=ui.tab, content="Итог").click()
            await user.should_see("Ваш результат")
            user.find(kind=ui.tab, content="Рейтинг").click()
            await user.should_see("Результаты участников", retries=40)
            await user.open("/admin")
            await user.should_see("Новая игра", retries=40)
            user.find(kind=ui.tab, content="Участники").click()
            await user.should_see("Подробнее", retries=40)
            user.find("Подробнее").click()
            await user.should_see("Закрыть", retries=40)
            user.find(kind=ui.button, content="Закрыть").click()
            user.find(kind=ui.button, content="Заблокировать").click()
            await user.should_see("Причина (10–500 символов)")
            user.find("Причина (10–500 символов)").type("Проверка блокировки NiceGUI")
            user.find(kind=ui.button, content="Подтвердить").click()
            await user.should_see("Разблокировать", retries=40)
            user.find("Разблокировать").click()
            await user.should_see("Причина (10–500 символов)")
            user.find("Причина (10–500 символов)").type(
                "Проверка разблокировки NiceGUI"
            )
            user.find(kind=ui.button, content="Подтвердить").click()
            await user.should_see("Заблокировать", retries=40)
            user.find(kind=ui.tab, content="Аудит").click()
            await user.should_see("Последние события", retries=40)
            user.find(kind=ui.tab, content="Результаты").click()
            await user.should_see("Обновить", retries=40)
            user.find(kind=ui.tab, content="Игра").click()
            user.find("Новая игра").click()
            await user.should_see("Подтвердить")
            user.find(kind=ui.button, content="Подтвердить").click()
            await user.should_see("Ожидаем начала игры", retries=40)
            await user.should_see("Сохранить настройки", retries=40)
            await front.api.close()

    asyncio.run(run())


@pytest.mark.parametrize("revoked", [False, True])
def test_reconnect_checks_session(api, player, tmp_path, monkeypatch, revoked):
    from nicegui import app
    from nicegui.nicegui import _on_handshake
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.ui.nicegui.client import APIClient

    monkeypatch.setattr(Storage, "path", tmp_path)
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path))

    async def run():
        checks = []
        backend = httpx.ASGITransport(api.app)

        async def route(request):
            if request.method == "GET" and request.url.path.endswith("/auth/session"):
                checks.append(request)
            return await backend.handle_async_request(request)

        async with user_simulation() as user:
            front = importlib.import_module("src.aml_workshop_simulator.ui.nicegui.app")
            await front.api.close()
            front.api = APIClient(
                "http://test/api/v1", transport=httpx.MockTransport(route)
            )
            await user.open("/play/login")
            token = player["headers"]["X-Session-ID"]
            with user:
                app.storage.user["auth_play"] = {"session_id": token}
            client = await user.open("/play")
            await user.should_see("Ожидаем начала игры", retries=40)
            if revoked:
                await front.api.request("DELETE", "auth/session", session_id=token)
            count = len(checks)
            # Exercise NiceGUI's actual disconnect/handshake lifecycle without a browser.
            socket_id, document_id = next(iter(client._socket_to_document_id.items()))
            with user:
                client.handle_disconnect(socket_id)
                await _on_handshake(
                    f"test-{uuid4()}",
                    {
                        "client_id": client.id,
                        "tab_id": user.tab_id,
                        "document_id": document_id,
                    },
                )
            await asyncio.sleep(0.3)
            assert len(checks) > count
            if revoked:
                await user.should_see("Войти", retries=40)
                with user:
                    assert "auth_play" not in app.storage.user
                    assert "workspace_play" not in app.storage.user
            else:
                assert user.client is client
                await user.should_see("Ожидаем начала игры")
                with user:
                    assert app.storage.user["auth_play"]["session_id"] == token
            await front.api.close()

    asyncio.run(run())


def test_state_load_failure_remains_visible_and_recovers(
    api, player, tmp_path, monkeypatch, caplog
):
    from nicegui import app
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.ui.nicegui.client import APIClient

    monkeypatch.setattr(Storage, "path", tmp_path)
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path))

    async def run():
        fail = True
        backend = httpx.ASGITransport(api.app)

        async def route(request):
            if request.url.path.endswith("/rounds/current/state") and fail:
                return httpx.Response(
                    503,
                    json={"code": "unavailable", "message": "Игра временно недоступна"},
                )
            return await backend.handle_async_request(request)

        async with user_simulation() as user:
            front = importlib.import_module("src.aml_workshop_simulator.ui.nicegui.app")
            await front.api.close()
            front.api = APIClient(
                "http://test/api/v1", transport=httpx.MockTransport(route)
            )
            await user.open("/play/login")
            with user:
                app.storage.user["auth_play"] = {
                    "session_id": player["headers"]["X-Session-ID"]
                }
            await user.open("/play")
            await user.should_see("Игра временно недоступна", retries=20)
            await asyncio.sleep(0.6)
            await user.should_see("Игра временно недоступна")
            fail = False
            await user.should_see("Ожидаем начала игры", retries=50)
            assert not [r for r in caplog.records if r.levelname == "ERROR"]
            await front.api.close()

    asyncio.run(run())
