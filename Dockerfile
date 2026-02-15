FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

# Upgrade packaging tools first (helps with SSL/wheels in some networks)
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install deps with retries & longer timeout (fixes flaky networks)
RUN pip install --no-cache-dir --retries 10 --timeout 120 --index-url https://pypi.org/simple -r /app/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY app /app/app
COPY README.md /app/README.md

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4}"]
