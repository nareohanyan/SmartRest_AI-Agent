# Operations Guide

Last updated: 2026-04-22

## Environments

Current environment styles:

- `development`
- `local_acceptance`
- `staging`
- `production`

Strict environments validate required configuration more aggressively than development.

Key configuration source:

- [app/core/config.py](../app/core/config.py)
- [.env.example](../.env.example)

## Main Commands

Primary operational entrypoints are in [Makefile](../Makefile).

Most useful commands:

- `make setup`
- `make lint`
- `make typecheck`
- `make test`
- `make test-integration`
- `make test-post-sync`
- `make migrate-smartrest`
- `make migrate-chat-analytics`
- `make sync-toon-identities`
- `make sync-toon-smartrest`
- `make run-8010`

## Quality Gates

Current practical gates:

- `ruff check .`
- `mypy app`
- `pytest`

Notes:

- `mypy app` is the meaningful enforced typecheck today
- full `mypy app tests` still has unrelated test typing backlog and is not the primary gate

## Databases

There are multiple storage roles in this repository.

## 1. SmartRest Operational Postgres

Used for:

- application-side operational data
- reports
- synced business tables

## 2. Chat Analytics Postgres

Used for:

- run persistence
- messages
- execution traceability

## 3. Source-Side MariaDB/MySQL

Used for:

- sync source data

## Migrations

Two Alembic tracks exist:

- `migrations/smartrest`
- `migrations/chat_analytics`

Standard sequence:

1. start databases
2. run smartrest migrations
3. run chat analytics migrations
4. run sync flows if needed
5. run validation tests

## Sync Operations

Sync is part of the real system, not dead scaffolding.

Key runners:

- [app/sync/runner.py](../app/sync/runner.py)
- [app/sync/mapped_runner.py](../app/sync/mapped_runner.py)
- [app/sync/mapped_table_sync.py](../app/sync/mapped_table_sync.py)

Recommended order:

1. `make sync-toon-identities`
2. `make sync-toon-smartrest`
3. `make test-post-sync`

## Local Bring-Up Runbook

Minimal local flow:

1. `cp .env.example .env`
2. create `.venv`
3. install dependencies
4. `docker compose --profile db up -d smartrest_db database`
5. `make migrate-smartrest`
6. `make migrate-chat-analytics`
7. `make test`
8. start the app
9. verify `/health`

## Incident-Oriented Troubleshooting

## Service boots but analytics answers are wrong

Check in this order:

1. parser/planning interpretation
2. capability restrictions
3. tool execution path
4. tenant data quality
5. response rendering

## Queries return no results

Check:

- correct `profile_id`
- date range
- whether synced data exists
- whether the question is hitting a supported metric/dimension path
- whether exclusion/filter logic removed all rows

## Armenian answer is awkward but factually correct

Likely layer:

- response rendering, not execution

Relevant files:

- [app/agent/response_text.py](../app/agent/response_text.py)
- [app/agent/llm/response.py](../app/agent/llm/response.py)

## Question is rejected or unsupported unexpectedly

Likely layer:

- parser/planning/policy

Relevant files:

- [app/agent/planning.py](../app/agent/planning.py)
- [app/agent/parser_concepts.py](../app/agent/parser_concepts.py)
- [app/agent/planning_policy.py](../app/agent/planning_policy.py)

## Access or scope behavior looks wrong

Treat as high severity.

Relevant files:

- [app/core/auth.py](../app/core/auth.py)
- [app/services/subscription_access.py](../app/services/subscription_access.py)
- [app/agent/report_tools.py](../app/agent/report_tools.py)

## Suggested Ongoing Maintenance

- keep README and handoff docs updated when architectural behavior changes
- add focused tests whenever parser semantics or response behavior changes
- document product semantics before broadening colloquial language support
- review dependency alignment when DB/runtime assumptions change
