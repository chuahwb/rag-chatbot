.PHONY: help dev dev-all dev-docker test lint format ingest seed

PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff

help:
	@echo "Available targets:"
	@echo "  make dev      # Run FastAPI server with autoreload"
	@echo "  make dev-all  # Run API + Vite dev server in one terminal"
	@echo "  make dev-docker # Run the docker compose dev stack"
	@echo "  make test     # Run pytest suite"
	@echo "  make lint     # Run Ruff lint checks"
	@echo "  make format   # Run Ruff formatter"
	@echo "  make ingest   # Build the products vector store (requires script)"
	@echo "  make seed     # Seed the outlets database (requires script)"

dev:
	WATCHFILES_FORCE_POLLING=true PYTHONPATH=server $(UVICORN) app.main:create_app --factory \
		--host 0.0.0.0 --port 8000 --reload \
		--reload-dir server/app \
		--reload-dir server/scripts \
		--reload-exclude 'web/*' \
		--reload-exclude 'node_modules/*' \
		--reload-exclude '.venv/*' \
		--reload-exclude 'data/*'

dev-all:
	@bash -c "set -euo pipefail; trap 'kill 0' INT TERM EXIT; \
		($(MAKE) dev) & \
		(cd web && npm run dev) & \
		wait"

dev-docker:
	docker compose up --build

test:
	PYTHONPATH=server $(PYTEST)

lint:
	PYTHONPATH=server $(RUFF) check server

format:
	PYTHONPATH=server $(RUFF) format server

ingest:
	PYTHONPATH=server $(PYTHON) server/scripts/ingest_products.py

seed:
	PYTHONPATH=server $(PYTHON) server/scripts/seed_outlets.py



