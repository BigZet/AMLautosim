"""Canonical operation channels.

`Channel` is the *global* set of channel values the system knows about. It is the
only place where a channel string becomes a legal value at schema level.

Which of those values a concrete step may actually use is **not** decided here:
it is declared per card version in `parameter_schema.channels`
(see `domain.catalog`) and is enforced by `domain.rules`. A value that exists in
this enum is therefore not automatically acceptable for a card.

No aliasing is permitted: `bank` and `branch` are distinct channels.
"""

from __future__ import annotations

from enum import StrEnum

from src.aml_workshop_simulator.core.game_config import load_config

CHANNEL_LABELS: dict[str, str] = load_config("channels.json")
Channel = StrEnum("Channel", {code: code for code in CHANNEL_LABELS})


ALL_CHANNELS: tuple[str, ...] = tuple(channel.value for channel in Channel)


def channel_label(value: str) -> str:
    """Human label for a known channel, or the raw value for an unknown one."""
    return CHANNEL_LABELS.get(value, value)
