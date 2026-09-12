"""Run with: python -m src.aml_workshop_simulator.ui.nicegui.app."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

# NiceGUI reads its storage path at import time. Never store it in source folders.
STORAGE_PATH = Path(os.environ.setdefault("NICEGUI_STORAGE_PATH", ".nicegui")).resolve()
STORAGE_PATH.mkdir(mode=0o700, parents=True, exist_ok=True)

from nicegui import app, ui
from pydantic import ValidationError
from starlette.responses import RedirectResponse

from . import auth, theme
from .client import SESSION_ERRORS, APIClient, APIError

api = APIClient(
    os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
)
app.on_shutdown(api.close)


@ui.page("/")
def root():
    return RedirectResponse("/play")


@app.get("/health/live")
def live():
    return {"status": "ok", "service": "nicegui"}


async def existing_login(audience):
    if not auth.credential(app.storage.user, audience):
        return False
    try:
        return await auth.verify(api, app.storage.user, audience) is not None
    except APIError:
        return False


def page_owner(storage, audience):
    client = ui.context.client

    def claim():
        pages = dict(storage.get("pages", {}))
        pages[client.tab_id] = client.id
        storage["pages"] = pages

    client.on_connect(claim)
    return lambda: storage.get("pages", {}).get(client.tab_id) == client.id


async def auth_page(audience="play", register=False):
    if await existing_login(audience):
        return RedirectResponse("/" + audience)
    theme.setup()
    storage = app.storage.user
    owns_page = page_owner(storage, audience)
    form = theme.auth_layout(audience)
    busy = False
    cooldown_until = 0.0
    import time

    with form:
        if audience == "admin":
            ui.label("Вход организатора").classes("form-title")
        if audience == "play":
            with ui.element("nav").classes("auth-switch"):
                ui.link("Вход", "/play/login").classes(
                    "selected" if not register else ""
                )
                ui.link("Регистрация", "/play/register").classes(
                    "selected" if register else ""
                )
        success = ui.label().classes("success-box")
        success.set_visibility(False)
        error = ui.label().classes("error-box").props("role=alert")
        notice = storage.pop(f"notice_{audience}", None)
        error.set_text(notice or "")
        error.set_visibility(bool(notice))
        fields = {}
        if register:
            fields["display_name"] = (
                ui.input("Имя участника", placeholder="Как к вам обращаться")
                .props("outlined autocomplete=name maxlength=120")
                .classes("w-full")
            )
        fields["email"] = (
            ui.input("Email", placeholder="you@example.com")
            .props("outlined type=email autocomplete=username")
            .classes("w-full")
        )
        fields["password"] = (
            ui.input("Пароль", password=True, password_toggle_button=True)
            .props(
                "outlined maxlength=128 autocomplete="
                + ("new-password" if register else "current-password")
            )
            .classes("w-full")
        )
        if register:
            ui.label("От 10 до 128 символов.").classes("form-note -mt-3")
            fields["confirmation"] = (
                ui.input("Повторите пароль", password=True, password_toggle_button=True)
                .props("outlined autocomplete=new-password maxlength=128")
                .classes("w-full")
            )

        def show_error(message):
            error.set_text(message)
            error.set_visibility(True)

        async def submit():
            nonlocal busy, cooldown_until, register
            if busy or not owns_page() or time.monotonic() < cooldown_until:
                return
            error.set_visibility(False)
            for field in fields.values():
                field.props(remove="error error-message")
            email = (fields["email"].value or "").strip()
            password = fields["password"].value or ""
            if not email or not password:
                show_error("Укажите email и пароль.")
                return
            if register:
                if password != fields["confirmation"].value:
                    fields["confirmation"].props(
                        'error error-message="Пароли не совпадают"'
                    )
                    return
                try:
                    payload = auth.Registration(
                        email=email,
                        password=password,
                        display_name=(fields["display_name"].value or "").strip(),
                    )
                except ValidationError as exc:
                    messages = {
                        "email": "Введите корректный email.",
                        "display_name": "Имя должно содержать от 2 до 120 символов.",
                        "password": "Пароль должен содержать от 10 до 128 символов.",
                    }
                    for violation in exc.errors():
                        name = str(violation["loc"][0])
                        if name in fields:
                            fields[name].props(
                                f'error error-message="{messages[name]}"'
                            )
                    return
            busy = True
            button.props("loading")
            for field in fields.values():
                field.disable()
            try:
                if register:
                    await api.request(
                        "POST", "auth/register", body=payload.model_dump()
                    )
                    # A failed login must not repeat registration on the next click.
                    register = False
                    success.set_text("Аккаунт создан. Выполняем вход…")
                    success.set_visibility(True)
                    button.set_text("Войти")
                    fields["display_name"].set_visibility(False)
                    fields["confirmation"].set_visibility(False)
                if await auth.login(api, storage, audience, email, password):
                    fields["password"].set_value("")
                    if "confirmation" in fields:
                        fields["confirmation"].set_value("")
                    ui.navigate.to("/" + audience)
            except APIError as exc:
                message = exc.message
                if exc.code == "login_temporarily_locked":
                    seconds = max(1, exc.retry_after or 30)
                    cooldown_until = time.monotonic() + seconds
                    message += f" Попробуйте через {seconds} сек."
                if success.visible:
                    success.set_text(
                        "Аккаунт уже создан. Войдите с указанными email и паролем."
                    )
                show_error(message)
            except ValidationError:
                show_error(
                    "Ответ сервера не соответствует ожидаемому формату. Попробуйте позже."
                )
            finally:
                fields["password"].set_value("")
                if "confirmation" in fields:
                    fields["confirmation"].set_value("")
                busy = False
                button.props(remove="loading")
                for field in fields.values():
                    field.enable()

        button = (
            ui.button("Зарегистрироваться" if register else "Войти", on_click=submit)
            .props("unelevated no-caps")
            .classes("primary-button")
        )
        for field in fields.values():
            field.on("keydown.enter", submit)

        def cooldown():
            if not busy:
                button.set_enabled(time.monotonic() >= cooldown_until)

        ui.timer(1, cooldown)


@ui.page("/play/login")
async def play_login():
    return await auth_page()


@ui.page("/play/register")
async def play_register():
    return await auth_page(register=True)


@ui.page("/admin/login")
async def admin_login():
    return await auth_page("admin")


async def protected_page(audience):
    storage = app.storage.user
    try:
        identity = await auth.verify(api, storage, audience)
    except APIError as exc:
        if not auth.credential(storage, audience):
            return RedirectResponse(f"/{audience}/login")
        theme.setup()
        with theme.auth_layout(audience):
            ui.label("Не удалось подключиться").classes("form-title")
            ui.label(exc.message).classes("error-box")
            ui.button(
                "Повторить", on_click=lambda: ui.navigate.to("/" + audience)
            ).props("no-caps")
        return None
    if identity is None:
        return RedirectResponse(f"/{audience}/login")
    theme.setup()
    token = auth.credential(storage, audience)
    game_status = None
    with ui.row().classes("app-header"):
        with ui.row().classes("header-identity"):
            theme.brand()
            game_title = ui.label().classes("header-game-title")
            game_title.set_visibility(False)
        ui.space()
        if audience == "play":
            game_status = ui.label().classes("header-game-status")
            game_status.set_visibility(False)
        ui.label(identity.display_name).classes("header-user-name")

        async def sign_out():
            try:
                await auth.logout(api, storage, audience)
            except APIError:
                storage[f"notice_{audience}"] = (
                    "Вход на этом устройстве завершён. Не удалось подтвердить отзыв сессии на сервере."
                )
            ui.navigate.to(f"/{audience}/login")

        with ui.row().classes("header-actions"):
            with (
                ui.link("Об игре", f"/about?audience={audience}", new_tab=True)
                .classes("header-text-link")
                .tooltip("Открыть описание игры в новой вкладке")
            ):
                ui.icon("menu_book").props('aria-hidden="true"')
            ui.button(on_click=sign_out, icon="logout").props(
                'flat dense aria-label="Выйти"'
            ).classes("header-exit").tooltip("Выйти")
    with ui.column().classes("workspace"):
        if audience == "admin":
            ui.label("Панель организатора").classes("text-3xl font-semibold")
        connection = ui.label().classes("error-box")
        connection.set_visibility(False)
        content = ui.column().classes("w-full gap-4")
    client = ui.context.client
    owns_page = page_owner(storage, audience)

    async def guarded(work, *, clear_error=True):
        if not owns_page() or not client.has_socket_connection:
            return None
        if auth.credential(storage, audience) != token:
            ui.navigate.to(f"/{audience}/login")
            return None
        try:
            result = await work()
            if (
                clear_error
                and owns_page()
                and auth.credential(storage, audience) == token
            ):
                connection.set_visibility(False)
            return result
        except APIError as exc:
            if not owns_page() or auth.credential(storage, audience) != token:
                return None
            if exc.code in SESSION_ERRORS | {"account_blocked", "forbidden"}:
                auth.invalidate(storage, audience)
                storage[f"notice_{audience}"] = exc.message
                ui.navigate.to(f"/{audience}/login")
                return None
            connection.set_text(exc.message)
            connection.set_visibility(True)
            return None

    async def reconnect():
        async def check():
            await api.request("GET", "auth/session", session_id=token)

        # Recheck even when the current screen has no pending game requests.
        # Business requests independently enforce role and audience in FastAPI.
        await guarded(check, clear_error=False)

    client.on_connect(reconnect)

    with content:
        if audience == "play":
            from .participant import ParticipantScreen

            screen = ParticipantScreen(
                api, storage, token, guarded, game_status, game_title
            )
        else:
            from .organizer import OrganizerScreen

            screen = OrganizerScreen(api, storage, token, guarded, game_title)
    ui.timer(3, screen.poll)


@ui.page("/play")
async def play():
    return await protected_page("play")


@ui.page("/admin")
async def admin():
    return await protected_page("admin")


@ui.page("/about")
def about(audience: str = "play"):
    from .about import render_about

    render_about(audience)


def storage_secret():
    configured = os.environ.get("NICEGUI_STORAGE_SECRET")
    if configured:
        return configured
    # A stable local secret makes reloads and process restarts keep the UI cookie.
    # Production supplies NICEGUI_STORAGE_SECRET and a private writable volume.
    path = STORAGE_PATH / ".secret"
    try:
        with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    return path.read_text().strip()


if __name__ == "__main__":
    ui.run(
        host=os.environ.get("UI_HOST", "127.0.0.1"),
        port=int(os.environ.get("UI_PORT", "8080")),
        title="AML Практикум",
        language="ru",
        reload=False,
        show=False,
        storage_secret=storage_secret(),
        session_middleware_kwargs={
            "session_cookie": "aml_ui",
            "same_site": "lax",
            "https_only": os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        },
    )
