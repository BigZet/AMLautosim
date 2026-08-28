FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src
COPY .streamlit ./.streamlit

EXPOSE 8000 8501 8502

CMD ["uvicorn", "src.aml_workshop_simulator.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
