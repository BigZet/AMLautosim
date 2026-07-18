from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from backend.app.domain.enums import RiskLabel, RoundStatus, ScenarioStatus, UserRole


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: UserRole

    model_config = {"from_attributes": True}


class ActionCardOut(BaseModel):
    id: int
    code: str
    title: str
    description: str
    category: str
    risk_weight: float

    model_config = {"from_attributes": True}


class RoundCreateIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)


class RoundOut(BaseModel):
    id: int
    title: str
    status: RoundStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ScenarioStep(BaseModel):
    card_code: str
    amount: float = Field(ge=0)
    recipient_type: str
    country_risk: str
    frequency: int = Field(ge=1, le=20)


class ScenarioSubmitIn(BaseModel):
    round_id: int
    steps: list[ScenarioStep] = Field(min_length=1, max_length=12)


class ScenarioOut(BaseModel):
    id: int
    round_id: int
    participant_id: int
    status: ScenarioStatus
    steps: list[dict]
    submitted_at: datetime | None

    model_config = {"from_attributes": True}


class ScoringResultOut(BaseModel):
    scenario_id: int
    risk_score: float
    label: RiskLabel
    explanation: dict

    model_config = {"from_attributes": True}


class BoardRowOut(BaseModel):
    participant_name: str
    scenario_id: int
    risk_score: float
    label: RiskLabel
    top_factors: list[dict]


class RoundStatsOut(BaseModel):
    round_id: int
    registered_users: int
    submitted_scenarios: int
    scored_scenarios: int
