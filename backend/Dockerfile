# X FACTOR backend — FastAPI + LangGraph supervisor.
#
# Build:  docker build -t xfactor-backend ./backend
# Run:    docker run --env-file backend/.env -p 8000:8000 xfactor-backend
#
# The application reads configuration from environment variables only; never
# bake a .env file into the image.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so source edits do not invalidate the pip layer.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY demo ./demo

# Run as an unprivileged user; the app writes nothing to disk.
RUN useradd --create-home --uid 10001 xfactor \
    && chown -R xfactor:xfactor /app
USER xfactor

EXPOSE 8000

# Liveness only: it intentionally does not require PostgreSQL, so a database
# restart does not mark the API container unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3)"]

# No --reload: production-style single process. Uvicorn handles SIGTERM, which
# runs the FastAPI lifespan shutdown hook.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
