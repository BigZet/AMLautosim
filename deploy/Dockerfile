# Download the locked binary wheels in a separate stage.
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt ./
# Fail explicitly if the target platform lacks a wheel instead of resolving
# extra build dependencies outside the runtime lock.
RUN pip download --only-binary=:all: --dest /wheels -r requirements.txt


# Runtime stage.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src
COPY config ./config

# The application only reads its own code; it never writes into /app.
# NiceGUI persists browser sessions in its private writable volume.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /home/app/nicegui \
    && chown app:app /home/app/nicegui \
    && chmod 700 /home/app/nicegui \
    && chown -R root:root /app \
    && chmod -R a-w /app
ENV HOME=/home/app
USER app

EXPOSE 8000 8080

CMD ["uvicorn", "src.aml_workshop_simulator.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
