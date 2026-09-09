"""Administrator routes."""

from fastapi import APIRouter

from . import audit, leaderboard, participants, rounds

router = APIRouter()
for child in (rounds, participants, leaderboard, audit):
    router.include_router(child.router)
