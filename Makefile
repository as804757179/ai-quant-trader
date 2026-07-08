.PHONY: up down dev test migrate seed backfill init logs shell

up:
	docker compose up -d

down:
	docker compose down

dev:
	docker compose -f docker-compose.dev.yml up

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python scripts/seed_stocks.py

backfill:
	docker compose exec api python scripts/backfill_kline.py --years=3

init:
	docker compose exec api python scripts/init_simulation_account.py --cash 1000000

test:
	docker compose exec api pytest tests/ -v --cov=app

logs:
	docker compose logs -f api worker

shell:
	docker compose exec api bash