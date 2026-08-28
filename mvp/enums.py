from enum import StrEnum


class UserRole(StrEnum):
    participant = "participant"
    admin = "admin"


class RoundStatus(StrEnum):
    draft = "draft"
    active = "active"
    scoring = "scoring"
    completed = "completed"


class ScenarioStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    scored = "scored"


class RiskLabel(StrEnum):
    normal = "normal"
    review = "review"
    suspicious = "suspicious"

