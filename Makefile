.PHONY: help deploy start stop restart logs build clean dev test

# Default target
help:
	@echo "🤖 Velox Bot - Available Commands:"
	@echo ""
	@echo "  make deploy      - Pull changes, rebuild & restart (full deploy)"
	@echo "  make quick       - Quick restart without rebuild"
	@echo "  make start       - Start containers"
	@echo "  make stop        - Stop containers"
	@echo "  make restart     - Restart containers"
	@echo "  make logs        - Show logs (follow)"
	@echo "  make build       - Build images"
	@echo "  make clean       - Stop & remove containers + volumes"
	@echo "  make dev         - Start in dev mode (with hot reload)"
	@echo "  make test        - Run tests"
	@echo "  make status      - Show container status"
	@echo "  make shell       - Open shell in bot container"
	@echo "  make db-shell    - Open MongoDB shell"

deploy:
	@./deploy.sh

quick:
	@echo "⚡ Quick restart..."
	@git pull origin main
	@docker compose restart bot
	@echo "✅ Done! Run 'make logs' to check"

start:
	@echo "🚀 Starting containers..."
	@docker compose up -d
	@docker compose ps

stop:
	@echo "🛑 Stopping containers..."
	@docker compose down

restart:
	@echo "🔄 Restarting containers..."
	@docker compose restart
	@docker compose ps

logs:
	@docker compose logs -f --tail=100

build:
	@echo "🔨 Building images..."
	@docker compose build

clean:
	@echo "🧹 Cleaning up..."
	@docker compose down -v
	@docker system prune -af --volumes
	@echo "✅ Cleaned!"

dev:
	@echo "🔧 Starting in dev mode..."
	@docker compose -f docker-compose.dev.yml up

test:
	@echo "🧪 Running tests..."
	@docker compose exec bot python -m pytest

status:
	@docker compose ps

shell:
	@docker compose exec bot /bin/bash

db-shell:
	@docker compose exec mongo mongosh hyperliquid_bot
