"""A persistent operation card keyed by step identity; GameEditor owns all writes."""

from copy import deepcopy
from uuid import uuid4
from nicegui import ui
from .money_input import MoneyInput
from ..counterparties import (
    editable_params,
    expanded,
    party_selector,
    party_name,
    party_options,
)
from ..aml_context import explanation_selector
from ..operation_timeline import timeline_control
from .resource_summary import display_number, display_operation_amount, display_moment


class StepCard:
    def __init__(self, screen, step, *, index):
        self.screen = screen
        self.step_id = step["step_id"]
        self.step = step
        self.index = index
        self.updating = False
        self.timeline = None
        self.card = None
        self.shape = deepcopy(self._shape(step))
        self._build(step, index)

    @staticmethod
    def _shape(step):
        return (step["card"], step.get("action_details", {}).get("incoming_kind"))

    def _build(self, step, index):
        screen = self.screen
        config = screen.editor.state["round"]["game_config"]
        timing = screen.step_timing
        self.moment = display_moment(timing[index]["occurred_at"]) if timing else ""
        card = next(
            (
                c
                for c in screen.editor.cards
                if all(c[k] == step["card"][k] for k in ("id", "code", "version"))
            ),
            None,
        )
        if not card:
            self.element = ui.label(
                "Карточка недоступна. Обновите состояние игры."
            ).classes("error-box")
            return
        self.card = card
        identity = step.get("sender_id") or step.get("recipient_id")
        party = next(
            (
                party_name(p)
                for p in config.get("behavior", {}).get("counterparties", [])
                if p["id"] == identity
            ),
            "Сторона не выбрана" if card["code"] != "cash_withdrawal" else "Наличные",
        )
        moment = display_moment(timing[index]["occurred_at"]) if timing else ""
        amount_text = (
            display_operation_amount(step["amount"]) if step["amount"] else "—"
        )
        summary = f"{index + 1}. {card['title']} · {amount_text} ₽"
        caption = " · ".join(part for part in (party, moment) if part)

        def remember(e, step_id=step["step_id"]):
            if e.value:
                screen.open_steps.add(step_id)
            else:
                screen.open_steps.discard(step_id)

        with ui.expansion(
            summary,
            caption=caption,
            value=step["step_id"] in screen.open_steps,
            on_value_change=remember,
        ).classes("operation-card w-full") as operation:
            self.element = operation
            with operation.add_slot("header"):
                with ui.element("q-item-section").classes("operation-heading"):
                    with ui.row().classes("operation-name"):
                        self.name_label = ui.label(f"{index + 1}. {card['title']}")
                        self.amount_label = amount_label = ui.label(
                            f"{amount_text} ₽"
                        ).classes("operation-heading-amount")
                    self.caption_label = caption_label = ui.label(caption).classes(
                        "operation-caption"
                    )
                with (
                    ui.element("q-item-section")
                    .props("side")
                    .classes("operation-actions-slot")
                ):
                    actions = ui.row().classes("operation-actions")
                    actions.on("click.stop", lambda: None)
            with actions:

                def move(delta):
                    i = next(
                        i
                        for i, value in enumerate(screen.editor.steps)
                        if value["step_id"] == self.step_id
                    )
                    if screen.submitting or not screen.editor.editable:
                        return
                    j = i + delta
                    if 0 <= j < len(screen.editor.steps):
                        if (
                            j == 0
                            and screen.editor.steps[i].get("interval_minutes")
                            is not None
                        ):
                            ui.notify(
                                "При переносе в начало ожидание сбрасывается. При возврате задайте его заново."
                            )
                        screen.editor.steps[i], screen.editor.steps[j] = (
                            screen.editor.steps[j],
                            screen.editor.steps[i],
                        )
                        screen.changed()
                        screen.render_chain()

                # The newest step is displayed first: visually up means later.
                self.up_button = (
                    ui.button(icon="arrow_upward", on_click=lambda m=move: m(1))
                    .props(
                        'flat dense aria-label="Переместить вверх — выполнить позже"'
                    )
                    .tooltip("Вверх — выполнить позже")
                    .set_enabled(index < len(screen.editor.steps) - 1)
                )
                self.down_button = (
                    ui.button(icon="arrow_downward", on_click=lambda m=move: m(-1))
                    .props(
                        'flat dense aria-label="Переместить вниз — выполнить раньше"'
                    )
                    .tooltip("Вниз — выполнить раньше")
                    .set_enabled(index > 0)
                )

                def remove():
                    i = next(
                        i
                        for i, value in enumerate(screen.editor.steps)
                        if value["step_id"] == self.step_id
                    )
                    if not screen.submitting:
                        screen.editor.steps.pop(i)
                        screen.changed()
                        screen.render_chain()

                def duplicate(step_id=step["step_id"]):
                    if screen.submitting:
                        return
                    limit = screen.editor.state["round"]["game_config"]["objectives"][
                        "max_actions"
                    ]
                    if len(screen.editor.steps) >= limit:
                        ui.notify(
                            f"Доступно не более {limit} операций.",
                            type="warning",
                        )
                        return
                    copied = deepcopy(screen.current_step(step_id))
                    copied["step_id"] = str(uuid4())
                    screen.editor.steps.append(copied)
                    screen.changed()
                    screen.render_chain()

                ui.button(icon="content_copy", on_click=duplicate).props(
                    'flat dense aria-label="Копировать операцию"'
                ).tooltip("Копировать операцию")
                ui.button(icon="delete_outline", on_click=remove).props(
                    'flat dense aria-label="Удалить операцию"'
                ).classes("operation-delete").tooltip("Удалить операцию")
            with ui.element("div").classes("operation-fields") as self.fields:

                def amount(
                    e,
                    step_id=step["step_id"],
                    label=amount_label,
                    expansion=operation,
                ):
                    if not screen.submitting:
                        value = (
                            "" if e.value is None else str(e.value).replace(",", ".")
                        )
                        screen.current_step(step_id)["amount"] = value
                        formatted = display_operation_amount(value) if value else "—"
                        label.set_text(f"{formatted} ₽")
                        expansion.set_text(
                            f"{self.index + 1}. {card['title']} · {formatted} ₽"
                        )
                        screen.changed()

                minimum = float(card["min_amount"])
                maximum = float(card["max_amount"])
                MoneyInput(
                    "Сумма",
                    value=float(step["amount"]) if step["amount"] else None,
                    min=minimum,
                    max=maximum,
                    precision=2,
                    step=0.01,
                    suffix="₽",
                    on_change=amount,
                    validation={
                        "Укажите сумму": lambda value: value is not None,
                        f"Минимум {display_number(card['min_amount'])} ₽": lambda value, bound=minimum: (
                            value is None or value >= bound
                        ),
                        f"Максимум {display_number(card['max_amount'])} ₽": lambda value, bound=maximum: (
                            value is None or value <= bound
                        ),
                    },
                ).props("outlined dense hide-bottom-space inputmode=decimal").classes(
                    "operation-parameter operation-amount"
                )
                config = screen.editor.state["round"]["game_config"]
                for param in editable_params(card, config):
                    if config.get("schema_version") in (9, 10) and (
                        (
                            param["key"] == "bank_country"
                            and step["action_details"].get("incoming_kind")
                            != "bank_transfer"
                        )
                        or (card["code"] == "salary" and param["key"] == "income_basis")
                    ):
                        continue
                    if (
                        card["code"] == "incoming_transfer"
                        and param["namespace"] == "channel"
                        and len(param["options"]) == 1
                    ):
                        # The channel default is still stored when adding a step.
                        continue
                    target = (
                        step["action_details"]
                        if param["namespace"] == "action"
                        else step["context"]
                    )

                    def update(
                        e,
                        step_id=step["step_id"],
                        namespace=param["namespace"],
                        k=param["key"],
                    ):
                        if not screen.submitting:
                            current = screen.current_step(step_id)
                            current[
                                "action_details" if namespace == "action" else "context"
                            ][k] = e.value
                            if (
                                config.get("schema_version") in (9, 10)
                                and k == "incoming_kind"
                            ):
                                current["action_details"] = {"incoming_kind": e.value}
                                if e.value == "bank_transfer":
                                    current["action_details"]["bank_country"] = "RU"
                                _, options = party_options(
                                    config,
                                    current["card"]["code"],
                                    current["action_details"],
                                )
                                if current.get("sender_id") not in options:
                                    current["sender_id"] = next(iter(options), None)
                            screen.changed()
                            if (
                                config.get("schema_version") in (9, 10)
                                and k == "incoming_kind"
                            ):
                                screen.render_chain()

                    value = target.get(param["key"], param["default"])
                    if param["kind"] == "toggle":
                        ui.switch(
                            param["label"], value=bool(value), on_change=update
                        ).classes("operation-toggle").tooltip(
                            param.get("help") or param["label"]
                        )
                    elif len(param["options"]) == 1:
                        option = param["options"][0]
                        if target.get(param["key"]) != option["value"]:
                            target[param["key"]] = option["value"]
                            screen.changed()
                        ui.label(f"{param['label']}: {option['label']}").classes(
                            "text-sm muted"
                        )
                    else:
                        ui.select(
                            {o["value"]: o["label"] for o in param["options"]},
                            value=value,
                            label=param["label"],
                            on_change=update,
                        ).props("outlined dense options-dense").classes(
                            "operation-parameter"
                        ).tooltip(param.get("help") or param["label"])

                if expanded(config):

                    def select_party(
                        role,
                        identity,
                        step_id=step["step_id"],
                        heading=caption_label,
                        operation_moment=None,
                    ):
                        if not screen.submitting and screen.editor.editable:
                            screen.current_step(step_id)[role] = identity
                            if role in ("sender_id", "recipient_id"):
                                selected = next(
                                    (
                                        party_name(p)
                                        for p in config["behavior"]["counterparties"]
                                        if p["id"] == identity
                                    ),
                                    "Сторона не выбрана",
                                )
                                heading.set_text(
                                    " · ".join(v for v in (selected, self.moment) if v)
                                )
                            screen.changed()

                    party_selector(config, step, select_party)
                    explanation_selector(config, step, select_party)

                    def change_interval(value, step_id=step["step_id"]):
                        if (
                            not self.updating
                            and not screen.submitting
                            and screen.editor.editable
                        ):
                            screen.current_step(step_id)["interval_minutes"] = value
                            screen.changed()
                            screen.render_chain()

                    self.change_interval = change_interval
                    self.timeline = timeline_control(
                        timing[index], config, change_interval
                    )

    def update(self, step: dict, *, index: int) -> None:
        self.index = index
        screen = self.screen
        config = screen.editor.state["round"]["game_config"]
        timing = screen.step_timing
        self.moment = display_moment(timing[index]["occurred_at"]) if timing else ""
        if self._shape(step) != self.shape or step != self.step:
            self.shape = deepcopy(self._shape(step))
            old = self.element
            self.timeline = None
            self._build(step, index)
            old.delete()
        self.step = step
        if self.card is None:
            return
        amount = display_operation_amount(step["amount"]) if step["amount"] else "—"
        title = f"{index + 1}. {self.card['title']}"
        identity = step.get("sender_id") or step.get("recipient_id")
        party = next(
            (
                party_name(p)
                for p in config.get("behavior", {}).get("counterparties", [])
                if p["id"] == identity
            ),
            "Наличные"
            if self.card["code"] == "cash_withdrawal"
            else "Сторона не выбрана",
        )
        caption = " · ".join(v for v in (party, self.moment) if v)
        self.name_label.set_text(title)
        self.amount_label.set_text(f"{amount} ₽")
        self.caption_label.set_text(caption)
        self.element.set_text(f"{title} · {amount} ₽")
        self.element.set_value(self.step_id in screen.open_steps)
        self.up_button.set_enabled(index < len(screen.editor.steps) - 1)
        self.down_button.set_enabled(index > 0)
        self.updating = True
        try:
            if timing and index > 0:
                if self.timeline is None or self.timeline.is_deleted:
                    with self.fields:
                        self.timeline = timeline_control(
                            timing[index], config, self.change_interval
                        )
                else:
                    self.timeline.set_value(timing[index]["interval_minutes"])
            elif self.timeline is not None:
                self.timeline.delete()
                self.timeline = None
        finally:
            self.updating = False

    def delete(self):
        self.element.delete()
