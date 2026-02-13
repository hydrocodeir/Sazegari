#!/usr/bin/env bash
set -e
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi
python -m app.scripts.fetch_fonts || true
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
