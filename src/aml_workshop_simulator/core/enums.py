"""Enumerations the domain actually branches on.

Round, scenario and role statuses are plain strings everywhere in this codebase
and are constrained by the database. Mirroring them here only invited the two
copies to disagree, which they had: the round enum never listed `stopped`.
"""

from enum import Enum


class RiskLabel(str, Enum):
    normal = "normal"
    review = "review"
    suspicious = "suspicious"
