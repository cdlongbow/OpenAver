#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
uvicorn web.app:app --reload --reload-include 'locales/*.json' --host 127.0.0.1 --port 8000
