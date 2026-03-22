#!/usr/bin/env bash
# Start the Nesting Sandbox server
# Render sets PORT env var automatically; default to 8000 locally
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
