"""Authenticated identity shared by application operations."""

from dataclasses import dataclass

from src.aml_workshop_simulator.db.models.users import User


@dataclass(frozen=True)
class CurrentPrincipal:
    user: User
    audience: str

    @property
    def user_id(self) -> int:
        return int(self.user.id)

    @property
    def role(self) -> str:
        return str(self.user.role)
