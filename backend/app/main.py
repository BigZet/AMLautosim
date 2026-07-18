from fastapi import FastAPI

from backend.app.api import admin, auth, cards, rounds, scenarios


app = FastAPI(title="AML Workshop Simulator", version="0.1.0")

app.include_router(auth.router)
app.include_router(cards.router)
app.include_router(rounds.router)
app.include_router(scenarios.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

