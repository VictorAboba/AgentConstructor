#!/usr/bin/env bash
# Builds the UI (first run) and starts AgentConstructor on http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -q -r backend/requirements.txt; fi
if [ ! -d frontend/dist ]; then (cd frontend && npm install && npm run build); fi
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
