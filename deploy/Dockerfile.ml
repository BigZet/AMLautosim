# Standalone offline training environment; source/data are mounted explicitly.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 MPLCONFIGDIR=/tmp/matplotlib
COPY requirements-ml.txt /tmp/requirements-ml.txt
RUN pip install --only-binary=:all: -r /tmp/requirements-ml.txt && pip check
WORKDIR /workspace
RUN useradd --create-home --uid 10001 trainer
USER trainer
CMD ["python", "-m", "scripts.train_aml_catboost", "--help"]
