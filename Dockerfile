FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# On Postgres: run migrations then start scheduler.
# On SQLite (local): scheduler auto-creates tables.
CMD ["sh", "-c", "alembic upgrade head && python -m hedgefund.scheduler"]
