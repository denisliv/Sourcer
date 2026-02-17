FROM python:3.12-slim

WORKDIR /app

# System dependencies for asyncpg, bcrypt, Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium --with-deps

# Copy application code
COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/
COPY linkedin_api/ linkedin_api/
COPY create_admin.py .

EXPOSE 8000

# Run Alembic migrations on startup, then start uvicorn
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
