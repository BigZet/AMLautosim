"""Canonical operation channels.

`Channel` is the *global* set of channel values the system knows about. It is the
only place where a channel string becomes a legal value at schema level.

Which of those values a concrete step may actually use is **not** decided here:
it is declared per card version in `parameter_schema.channels`
(see `domain.catalog`) and is enforced by `domain.rules`. A value that exists in
this enum is therefore not automatically acceptable for a card — `pos` for
example is a known channel with a UI label that no card version currently
allows, and every request that uses it is rejected.

No aliasing is permitted: `bank` and `branch` are distinct channels.
"""

from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Every channel value the platform recognises."""

    bank = "bank"
    branch = "branch"
    atm = "atm"
    mobile = "mobile"
    web = "web"
    exchange = "exchange"
    pos = "pos"


CHANNEL_LABELS: dict[str, str] = {
    Channel.bank: "Банковское зачисление",
    Channel.branch: "Отделение банка",
    Channel.atm: "Банкомат",
    Channel.mobile: "Мобильное приложение",
    Channel.web: "Интернет-банк",
    Channel.exchange: "Криптобиржа",
    Channel.pos: "POS-терминал",
}

ALL_CHANNELS: tuple[str, ...] = tuple(channel.value for channel in Channel)


def channel_label(value: str) -> str:
    """Human label for a known channel, or the raw value for an unknown one."""
    return CHANNEL_LABELS.get(value, value)
