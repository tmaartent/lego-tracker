# Build from the repo root: the shared event contracts live in libs/.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY libs/events /libs/events
COPY services/watcher .
RUN pip install --no-cache-dir /libs/events ".[dev]"

EXPOSE 8001
CMD ["sh", "-c", "alembic upgrade head && uvicorn watcher.main:app --host 0.0.0.0 --port 8001"]
