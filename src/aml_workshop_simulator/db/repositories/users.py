from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.schemas.auth import UserCreate
from src.aml_workshop_simulator.core.security import get_password_hash
from datetime import datetime, timezone


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(
            self,
            user_create: UserCreate,
            role: str = "participant") -> User:
        user = User(
            email=user_create.email,
            display_name=user_create.display_name,
            hashed_password=get_password_hash(user_create.password),
            role=role,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
