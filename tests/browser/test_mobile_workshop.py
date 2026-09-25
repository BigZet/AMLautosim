import pytest
from uuid import uuid4

pytestmark = pytest.mark.browser


def saved(page):
    page.get_by_text("Сохранено", exact=True).wait_for()


@pytest.mark.parametrize("width", [320, 360, 390, 430, 768, 1280])
def test_edit_correct_reorder_submit_and_result(
    scoring_participant, admin_api, workshop, width, capture
):
    page = scoring_participant
    page.set_viewport_size({"width": width, "height": 844})
    page.get_by_role("button", name="Добавить операцию", exact=True).click()
    page.get_by_role("button", name="Входящий перевод", exact=True).click()
    amount = page.get_by_label("Сумма", exact=True)
    amount.fill("0")
    page.get_by_text(
        "Введите положительную сумму с точностью до копейки.", exact=True
    ).wait_for()
    page.get_by_role("button", name="Исправить ошибку в операции", exact=True).wait_for(
        timeout=3000
    )
    amount.fill("")
    page.locator(".operation-name").click()
    capture(page, "invalid")
    page.get_by_role("button", name="Исправить ошибку в операции", exact=True).click()
    amount.wait_for()
    page.wait_for_function(
        "document.activeElement?.closest('.operation-amount') !== null"
    )
    amount.fill("12345,67")
    saved(page)
    amount.scroll_into_view_if_needed()
    page.wait_for_function(
        "!document.getAnimations().some(a => a.playState === 'running')"
    )
    amount.fill("23456,78")
    page.locator(".operation-heading-amount").filter(has_text="23 456,78").wait_for()
    amount.evaluate("e => window.retainedAmount = e")
    scroll = page.evaluate("scrollY")
    amount_y = amount.bounding_box()["y"]
    saved(page)
    assert amount.evaluate(
        "e => e === window.retainedAmount && document.activeElement === e"
    )
    # Browser scroll anchoring may adjust scrollY when the status line changes.
    # The focused field must retain its viewport position, with no large jump.
    assert abs(amount.bounding_box()["y"] - amount_y) < 3
    assert abs(page.evaluate("scrollY") - scroll) < 24
    capture(page, "editing")
    page.get_by_role("button", name="Добавить операцию", exact=True).click()
    page.get_by_role("button", name="Перевод по карте", exact=True).click()
    page.wait_for_function("document.querySelectorAll('.operation-card').length === 2")
    saved(page)
    cards = page.locator(".operation-card")
    cards.first.get_by_role("button", name="Действия", exact=True).click()
    page.get_by_role("button", name="Копировать операцию", exact=True).click()
    page.wait_for_function("document.querySelectorAll('.operation-card').length === 3")
    saved(page)
    cards.first.get_by_role("button", name="Действия", exact=True).click()
    page.get_by_role("button", name="Удалить операцию", exact=True).click()
    page.wait_for_function("document.querySelectorAll('.operation-card').length === 2")
    saved(page)
    first_id = cards.first.get_attribute("id")
    cards.first.get_by_role("button", name="Действия", exact=True).click()
    page.get_by_role(
        "button", name="Переместить вниз — выполнить раньше", exact=True
    ).click()
    page.wait_for_function(
        "id => document.querySelector('.operation-card').id !== id", arg=first_id
    )
    saved(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="Отправить сценарий", exact=True).click()
    page.get_by_role("button", name="Отправить", exact=True).click()
    page.get_by_text("Сценарий принят", exact=False).wait_for()
    capture(page, "submitted")
    organizer = page.context.new_page()
    organizer.goto(workshop["url"] + "/admin/login")
    organizer.get_by_label("Email", exact=True).fill("admin@example.com")
    organizer.get_by_label("Пароль", exact=True).fill(
        workshop["environment"]["AML_CI_ADMIN_PASSWORD"]
    )
    organizer.get_by_role("button", name="Войти", exact=True).click()
    organizer.get_by_role("button", name="Запустить скоринг", exact=True).click()
    organizer.get_by_role("button", name="Подтвердить", exact=True).click()
    page.get_by_text("Ваш результат", exact=False).first.wait_for(timeout=120000)
    assert page.locator(".shap-table:visible").count() == 0
    capture(page, "result")
    page.get_by_text("Что повлияло на оценку", exact=True).click()
    page.locator(".shap-table:visible").first.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.reload()
    page.get_by_text("Ваш результат", exact=False).first.wait_for()


def test_registration_on_mobile(page, workshop):
    page.set_viewport_size({"width": 360, "height": 740})
    page.goto(workshop["url"] + "/play/register")
    page.get_by_label("Имя участника", exact=True).fill("Новый участник")
    page.get_by_label("Email", exact=True).fill(f"register-{uuid4().hex}@example.com")
    password = uuid4().hex
    page.get_by_label("Пароль", exact=True).fill(password)
    page.get_by_label("Повторите пароль", exact=True).fill(password)
    page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    page.wait_for_url("**/play")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_saved_draft_reconnect_and_focus(participant):
    page = participant
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Добавить операцию", exact=True).click()
    page.get_by_role("button", name="Входящий перевод", exact=True).click()
    amount = page.get_by_label("Сумма", exact=True)
    amount.fill("23456.78")
    page.locator(".operation-heading-amount").filter(has_text="23 456,78").wait_for()
    saved(page)
    page.context.set_offline(True)
    page.wait_for_function("!navigator.onLine")
    page.context.set_offline(False)
    page.wait_for_function("navigator.onLine")
    page.reload()
    card = page.locator(".operation-card").first
    card.locator(".operation-name").click()
    amount = page.get_by_label("Сумма", exact=True)
    amount.wait_for()
    assert float(amount.input_value().replace(",", ".")) == 23456.78
    amount.fill("34567,89")
    amount.evaluate("e => e.setSelectionRange(3, 3)")
    saved(page)
    assert amount.evaluate(
        "e => document.activeElement === e && e.selectionStart === 3"
    )


def test_organizer_small_screen(page, workshop):
    page.set_viewport_size({"width": 360, "height": 740})
    page.goto(workshop["url"] + "/admin/login")
    page.get_by_label("Email", exact=True).fill("admin@example.com")
    page.get_by_label("Пароль", exact=True).fill(
        workshop["environment"]["AML_CI_ADMIN_PASSWORD"]
    )
    page.get_by_role("button", name="Войти", exact=True).click()
    page.wait_for_url("**/admin")
    page.get_by_text("Панель организатора", exact=True).wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("tab", name="Участники", exact=True).click()
    page.get_by_label("Поиск по имени или email", exact=True).wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_empty_primary_action(participant):
    page = participant
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.get_by_role("button", name="Добавить операцию", exact=True).is_visible()
    assert not page.get_by_role(
        "button", name="Отправить сценарий", exact=True
    ).is_visible()
