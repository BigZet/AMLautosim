"""Static guide to the workshop and participant workspace."""

from nicegui import ui

from . import theme


def render_about(audience="play"):
    target = "/admin" if audience == "admin" else "/play"
    theme.setup()
    with ui.row().classes("app-header"):
        theme.brand()
        ui.space()
        with ui.link("Вернуться к игре", target).classes(
            "header-action header-action-soft"
        ):
            ui.icon("arrow_back")
    with ui.column().classes("workspace game-guide"):
        with ui.column().classes("guide-intro"):
            ui.label("Об игре").classes("guide-eyebrow")
            ui.label("Соберите сценарий. Сравните результат.").classes("guide-title")
            ui.label(
                "AML Практикум — учебная игра о финансовых операциях и их оценке. "
                "Вы составляете последовательность операций, выполняете цель раунда "
                "и следите за ресурсами и ограничениями."
            ).classes("guide-lead")
        with ui.element("div").classes("guide-grid"):
            for number, title, description in [
                (
                    "01",
                    "Дождитесь старта",
                    "Организатор задаёт цель, доступные операции и лимиты. Когда игра начнётся, редактор откроется автоматически.",
                ),
                (
                    "02",
                    "Соберите сценарий",
                    "Добавляйте операции, меняйте суммы и параметры. Порядок шагов влияет на ресурсы — его можно менять стрелками.",
                ),
                (
                    "03",
                    "Отправьте на оценку",
                    "Выполните условия отправки и подтвердите сценарий. После отправки редактирование недоступно.",
                ),
                (
                    "04",
                    "Посмотрите результат",
                    "Организатор запускает оценку. Результат появится автоматически: итог, отправленные операции и рейтинг.",
                ),
            ]:
                with ui.card().classes("panel guide-step"):
                    ui.label(number).classes("guide-number")
                    ui.label(title).classes("text-lg font-semibold")
                    ui.label(description).classes("guide-copy")
        with ui.card().classes("panel guide-interface"):
            ui.label("Что где находится").classes("text-xl font-semibold")
            for icon, title, description in [
                (
                    "account_balance_wallet",
                    "Ресурсы — над редактором",
                    "Баланс, энергия, время и оставшиеся шаги показывают состояние после вашей текущей последовательности операций.",
                ),
                (
                    "touch_app",
                    "Карточки операций",
                    "Нажмите на карточку, чтобы добавить шаг. Сумма ограничена допустимым диапазоном; дополнительные параметры зависят от операции. Описание доступно в разделе «Об операции».",
                ),
                (
                    "swap_vert",
                    "Ваша последовательность",
                    "Стрелки меняют порядок шагов, значок копирования дублирует операцию, корзина удаляет её. Изменения сохраняются автоматически — проверяйте статус «Сохранено».",
                ),
                (
                    "checklist",
                    "Условия отправки — справа",
                    "Здесь видны остаток до цели и использованные лимиты. Галочки отмечают выполненные условия. Кнопка отправки становится доступной после выполнения условий и сохранения изменений.",
                ),
                (
                    "hourglass_top",
                    "Ожидание оценки",
                    "Подтверждение «Сценарий принят» означает, что отправка завершена. Можно просмотреть отправленные операции. Обновлять страницу не нужно.",
                ),
                (
                    "bar_chart",
                    "Вкладки результата",
                    "«Итог» показывает оценку, риск и сбережённые ресурсы. «Операции» — отправленную последовательность. «Рейтинг» — результаты участников, когда они доступны.",
                ),
            ]:
                with ui.row().classes("guide-feature"):
                    ui.icon(icon).classes("guide-feature-icon")
                    with ui.column().classes("guide-feature-text"):
                        ui.label(title).classes("font-semibold")
                        ui.label(description).classes("guide-copy")
        ui.label(
            "Цели и лимиты зависят от настроек текущей игры. Оценка используется в рамках учебного практикума."
        ).classes("guide-footnote")
