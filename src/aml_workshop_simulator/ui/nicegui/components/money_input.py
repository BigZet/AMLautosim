"""Locale-friendly monetary entry; API still receives canonical decimal strings."""

import re

from nicegui.elements.number import Number


class MoneyInput(Number):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.props('type=text inputmode=decimal autocomplete=off')

    def _event_args_to_value(self, event):
        raw = str(event.args or '').strip()
        # Reject grouping, exponent notation and mixed separators rather than
        # silently changing the amount pasted by the participant.
        if not re.fullmatch(r'\d+(?:[.,]\d{0,2})?', raw):
            return None
        return float(raw.replace(',', '.'))

    def _value_to_model_value(self, value):
        return '' if value is None else str(value)

