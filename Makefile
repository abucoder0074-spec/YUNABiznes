.PHONY: install db-up db-down migrate run test lint

install:
	python -m pip install -r backend/requirements.txt

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

run:
	cd backend && uvicorn app.main:app --reload

test:
	cd backend && pytest

lint:
	cd backend && ruff check .
