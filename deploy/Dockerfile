# Download the locked binary wheels in a separate stage.
FROM python:3.13.15-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0 AS builder

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt ./
# Fail explicitly if the target platform lacks a wheel instead of resolving
# extra build dependencies outside the runtime lock.
RUN pip download --only-binary=:all: --dest /wheels -r requirements.txt


# Runtime stage.
FROM python:3.13.15-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0

ARG GIT_SHA=development
ARG SOURCE_URL=https://github.com/BigZet/AMLautosim
LABEL org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.source=$SOURCE_URL
ENV GIT_SHA=$GIT_SHA

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
COPY resources/catboost_models/integration-v2-final ./resources/catboost_models/integration-v2-final
COPY resources/catboost_models/aml-game-v1 ./resources/catboost_models/aml-game-v1
COPY resources/catboost_models/aml-game-relaxed-v1 ./resources/catboost_models/aml-game-relaxed-v1
COPY resources/catboost_models/aml-game-attributes-v1 ./resources/catboost_models/aml-game-attributes-v1
COPY resources/catboost_models/aml-game-attribute-context-v1 ./resources/catboost_models/aml-game-attribute-context-v1
COPY resources/catboost_models/aml-game-organizer-settings-v1 ./resources/catboost_models/aml-game-organizer-settings-v1
COPY resources/catboost_models/aml-game-attribute-context-unlimited-v1 ./resources/catboost_models/aml-game-attribute-context-unlimited-v1

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
