# Build from the repo root: the shared event contracts live in libs/.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY libs/events /libs/events
COPY services/core .
RUN pip install --no-cache-dir /libs/events ".[dev]"

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
