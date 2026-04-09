SHELL := /bin/bash

.DEFAULT_GOAL := help

COMPOSE ?= docker compose
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PRE_COMMIT ?= .venv/bin/pre-commit
PRE_COMMIT_HOME ?= /tmp/pre-commit-cache
ALEMBIC ?= .venv/bin/alembic
ALEMBIC_SMARTREST ?= .venv/bin/alembic -c alembic-smartrest.ini
ENV_FILE ?= .env
MIGRATIONS_DIR ?= migrations/chat_analytics/versions
SMARTREST_MIGRATIONS_DIR ?= migrations/smartrest/versions

.PHONY: help setup up app-up db-up down down-v ps logs db-logs db-shell db-list db-chat-tables \
		build lint typecheck test test-integration test-post-sync test-all precommit quality \
		migrate current revision migrate-smartrest current-smartrest revision-smartrest \
		run-8010 sync-toon-identities sync-toon-smartrest sync-toon-smartrest-step

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

build:
	$(COMPOSE) build

run-8010:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload

up:
	$(COMPOSE) --profile db up -d

app-up: ## Start only app service in background.
	$(COMPOSE) up -d app

db-up: ## Start only Postgres service in background.
	$(COMPOSE) --profile db up -d smartrest_db

down:
	$(COMPOSE) down

down-v:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

db-logs: ## Follow logs for Postgres service only.
	$(COMPOSE) logs -f --tail=200 smartrest_db

db-shell:
	$(COMPOSE) exec smartrest_db psql -U smartrest -d smartrest

db-list:
	$(COMPOSE) exec smartrest_db psql -U smartrest -l

db-chat-tables:
	$(COMPOSE) exec smartrest_db psql -U smartrest -d chat_analytics_db -c "\dt"

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy app

test:
	$(PYTHON) -m pytest

test-integration:
	$(PYTHON) -m pytest -m integration

test-post-sync:
	$(PYTHON) -m pytest -m post_sync

test-all:
	$(PYTHON) -m pytest --run-all-tests

precommit:
	PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) $(PRE_COMMIT) run --all-files


migrate-chat-analytics:
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC) upgrade head

current-chat-analytics:
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC) current

revision-chat-analytics:
	@if [ -z "$(m)" ]; then \
		echo "Usage: make revision m='your message'"; \
		exit 1; \
	fi
	@mkdir -p $(MIGRATIONS_DIR)
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC) revision --autogenerate -m "$(m)"

migrate-smartrest:
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC_SMARTREST) upgrade head

current-smartrest:
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC_SMARTREST) current

revision-smartrest:
	@if [ -z "$(m)" ]; then \
		echo "Usage: make revision-smartrest m='your message'"; \
		exit 1; \
	fi
	@mkdir -p $(SMARTREST_MIGRATIONS_DIR)
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC_SMARTREST) revision --autogenerate -m "$(m)"

sync-toon-identities:
	@set -a; source $(ENV_FILE); set +a; $(PYTHON) -m app.sync.runner

sync-toon-smartrest:
	@set -a; source $(ENV_FILE); set +a; $(PYTHON) -m app.sync.mapped_runner

sync-toon-smartrest-step:
	@if [ -z "$(table)" ]; then \
		echo "Usage: make sync-toon-smartrest-step table=<src_or_dst_table> [batch=500]"; \
		exit 1; \
	fi
	@set -a; source $(ENV_FILE); set +a; $(PYTHON) -m app.sync.mapped_runner \
		--include-table "$(table)" \
		--batch-size "$(if $(batch),$(batch),500)" \
		--max-batches-per-table 1
