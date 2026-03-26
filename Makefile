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
	build lint typecheck test precommit quality migrate current revision migrate-smartrest \
	current-smartrest revision-smartrest

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

build:
	$(COMPOSE) build

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

db-list: ## List databases in the shared Postgres cluster.
	$(COMPOSE) exec smartrest_db psql -U smartrest -l

db-chat-tables:
	$(COMPOSE) exec smartrest_db psql -U smartrest -d chat_analytics_db -c "\dt"

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy app

test:
	$(PYTHON) -m pytest

precommit:
	PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) $(PRE_COMMIT) run --all-files

quality: lint typecheck test precommit ## Run full local quality gate.

migrate: ## Run chat analytics migrations.
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC) upgrade head

current: ## Show current chat analytics migration revision.
	@set -a; source $(ENV_FILE); set +a; $(ALEMBIC) current

revision:
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
