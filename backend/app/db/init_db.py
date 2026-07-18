from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import Base, SessionLocal, engine
from backend.app.domain.enums import UserRole
from backend.app.models.entities import ActionCard, User


DEFAULT_CARDS = [
    {
        "code": "salary_transfer",
        "title": "Обычный перевод зарплаты",
        "description": "Понятный источник и знакомый получатель.",
        "category": "baseline",
        "risk_weight": 2,
    },
    {
        "code": "split_transfer",
        "title": "Дробление суммы",
        "description": "Несколько похожих переводов вместо одного крупного.",
        "category": "structuring",
        "risk_weight": 24,
    },
    {
        "code": "new_counterparty",
        "title": "Новый получатель",
        "description": "Контрагент раньше не встречался в истории операций.",
        "category": "counterparty",
        "risk_weight": 12,
    },
    {
        "code": "cash_out",
        "title": "Быстрое снятие наличных",
        "description": "Средства быстро выводятся после поступления.",
        "category": "cash",
        "risk_weight": 22,
    },
    {
        "code": "cross_border",
        "title": "Трансграничный перевод",
        "description": "Операция связана с другой юрисдикцией.",
        "category": "geo",
        "risk_weight": 18,
    },
]


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for card_data in DEFAULT_CARDS:
            card = db.scalar(select(ActionCard).where(ActionCard.code == card_data["code"]))
            if card is None:
                db.add(ActionCard(**card_data))

        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        if admin is None:
            db.add(
                User(
                    email="admin@example.com",
                    display_name="Администратор",
                    hashed_password=hash_password("admin123"),
                    role=UserRole.admin,
                )
            )
        db.commit()


if __name__ == "__main__":
    init_db()
