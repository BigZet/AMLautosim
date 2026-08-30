# Build stage: compilers live here and never reach the runtime image.
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
# Resolve every dependency to a wheel once, so the runtime stage installs
# without a toolchain even when a pinned release ships no matching wheel.
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# Runtime stage.
FROM python:3.13-slim

# PYTHONPATH rather than an editable install: this is a src layout, and /app is
# made read-only below, so the package is put on the path instead of into
# site-packages.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

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
COPY .streamlit ./.streamlit

# The application only reads its own code; it never writes into /app.
# Streamlit still needs a writable HOME for its own runtime state.
RUN useradd --create-home --uid 10001 app \
    && chown -R root:root /app \
    && chmod -R a-w /app
ENV HOME=/home/app
USER app

EXPOSE 8000 8501 8502

CMD ["uvicorn", "aml_workshop_simulator.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
