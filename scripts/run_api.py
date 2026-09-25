"""Start bounded API workers; release migrations/seed run separately."""

import uvicorn

from src.aml_workshop_simulator.core.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "src.aml_workshop_simulator.api.main:app",
        host="0.0.0.0",
        port=8000,
        workers=settings.API_WORKERS,
        proxy_headers=False,
        access_log=False,
    )
