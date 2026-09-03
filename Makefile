.PHONY: install dev test lint format migrate seed reset-db

install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

dev:
	docker compose up

test:
	cd backend && pytest -v

lint:
	cd backend && ruff check . && mypy app
	cd frontend && npm run lint

format:
	cd backend && ruff format . && black .
	cd frontend && npm run format

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m scripts.seed_synthetic_data

reset-db:
	docker compose down -v postgres
	docker compose up -d postgres
