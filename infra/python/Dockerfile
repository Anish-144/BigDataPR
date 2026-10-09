# AgentShield Python image: FastAPI backend + batch jobs (lakehouse init,
# generator, detectors, evaluation). One image, different commands.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .
RUN useradd --create-home --uid 10001 agentshield && mkdir -p /app/benchmarks/results /app/state /app/models \
    && chown -R agentshield /app/benchmarks /app/state /app/models
USER agentshield

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
