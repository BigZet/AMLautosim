from enum import Enum


class UserRole(str, Enum):
    participant = "participant"
    admin = "admin"


class RoundStatus(str, Enum):
    draft = "draft"
    active = "active"
    scoring = "scoring"
    completed = "completed"


class ScenarioStatus(str, Enum):
    draft = "draft"
    submitted = "submitted"
    scored = "scored"


class RiskLabel(str, Enum):
    normal = "normal"
    review = "review"
    suspicious = "suspicious"
