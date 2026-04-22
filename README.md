# SmartRest AI Agent

SmartRest AI Agent is a bounded analytics backend for SmartRest business questions. It combines FastAPI, LangGraph, typed Pydantic contracts, OpenAI-assisted interpretation, SmartRest-backed retrieval, and runtime persistence.

The service is designed to answer reporting and analytics questions without turning the model into the source of business truth. Business numbers come from tools and database-backed services. The model is used for interpretation and response composition only.

## Status

Current repository state:

- structured FastAPI API boundary
- LangGraph runtime with typed shared state
- strict environment validation for non-development modes
- DB-backed scope resolution via canonical identity lookup
- DB-backed core reporting
- DB-backed live analytics retrieval for selected metric and dimension paths
- runtime persistence into a chat analytics database
- sync pipeline and post-sync validation tests
- broad unit and integration-oriented test coverage

The project is past prototype stage, but it is not fully hardened for production. The main remaining gaps are trust-boundary hardening, broader live analytics coverage, and stronger end-to-end strict-mode API validation.

## Documentation

Primary documents for maintainers and successors:

- [HANDOFF.md](HANDOFF.md)
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ONBOARDING.md](docs/ONBOARDING.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)

## What The Service Does

The service handles:

- signed tenant requests
- platform-admin assisted execution
- subscription access checks
- scope resolution
- report execution
- comparisons, rankings, trends, and selected business insights
- clarification and rejection handling
- onboarding-style responses for non-business smalltalk
- runtime persistence and execution tracing

This is not a generic chatbot and not a free-form NL-to-SQL agent.

## Architecture

```text
Client
  |
  v
FastAPI API Layer
  |
  v
Auth + Subscription Validation
  |
  v
Agent Runtime Service
  |
  v
LangGraph Workflow
  |         |             |                 |
  |         |             |                 +--> Runtime persistence
  |         |             |
  |         |             +--> OpenAI planning / response style layer
  |         |
  |         +--> Bounded tool registry
  |                |
  |                +--> scope tools
  |                +--> report tools
  |                +--> analytics tools
  |                +--> ranking / trend / calc tools
  |
  +--> SmartRest operational database
      Chat analytics database
      Sync pipeline
```

### Main Modules

- `app/api`: FastAPI application, routes, and API schemas
- `app/core`: configuration, logging, auth, runtime policy
- `app/services`: runtime service, identity, subscription, platform admin
- `app/agent`: graph, planning, policy, metrics, tools, live analytics services
- `app/reports`: report catalog and SmartRest-backed report backend
- `app/persistence`: runtime persistence and status mapping
- `app/smartrest`: SQLAlchemy models for the SmartRest operational DB
- `app/chat_analytics`: analytics persistence models
- `app/sync`: identity and mapped-table sync runners
- `tests`: unit, contract, graph, runtime, DB, and post-sync smoke tests

## Runtime Flow

Standard tenant request flow:

1. `POST /agent/run`
2. signed auth payload is verified
3. subscription access is checked
4. runtime persistence starts a run
5. LangGraph receives `AgentState`
6. scope is resolved
7. planning and policy determine the allowed route
8. report or analytics tools execute
9. grounded answer is composed
10. runtime persistence finalizes the run
11. API returns the response contract

Platform-admin flow:

1. `POST /agent/admin/run`
2. platform-admin signature is verified
3. target profile and user are resolved
4. optional subscription bypass is applied by configuration
5. runtime executes using the target tenant context

## API Surface

### `GET /health`

Returns a simple process-health response:

```json
{
  "status": "ok",
  "environment": "local_acceptance"
}
```

### `POST /agent/run`

Primary tenant execution endpoint.

Request shape:

```json
{
  "chat_id": "11111111-1111-1111-1111-111111111111",
  "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
  "auth": {
    "profile_nick": "demo_profile",
    "user_id": 101,
    "profile_id": 201,
    "current_timestamp": 1760000000,
    "token": "64-char-sha256-hex"
  },
  "scope_request": {
    "user_id": 101,
    "profile_id": 201,
    "profile_nick": "demo_profile",
    "metadata": {},
    "requested_branch_ids": null,
    "requested_export_mode": null
  }
}
```

Response shape:

```json
{
  "chat_id": "11111111-1111-1111-1111-111111111111",
  "run_id": "22222222-2222-2222-2222-222222222222",
  "status": "completed",
  "answer": "Total sales from 2026-03-01 to 2026-03-07 were 12345.67.",
  "selected_report_id": "sales_total",
  "applied_filters": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-07",
    "source": null
  },
  "warnings": [],
  "needs_clarification": false,
  "clarification_question": null
}
```

Possible statuses:

- `completed`
- `clarify`
- `rejected`
- `denied`
- `failed`
- `onboarding`

### `POST /agent/admin/profiles`

Lists tenant profiles available to a platform admin.

### `POST /agent/admin/run`

Executes the runtime for a target tenant using platform-admin credentials.

## Authentication Model

Tenant requests use a SHA-256 signature over:

```text
{current_timestamp}-{profile_nick}-{profile_id}-{user_id}
```

Platform-admin requests use:

```text
{current_timestamp}-{admin_id}
```

The code paths are implemented in `app/core/auth.py`.

Python example for building a tenant token:

```python
import hashlib
import time

secret = "your-secret"
current_timestamp = int(time.time())
profile_nick = "demo_profile"
profile_id = 201
user_id = 101

canonical_payload = f"{current_timestamp}-{profile_nick}-{profile_id}-{user_id}"
token = hashlib.sha256(f"{secret}-{canonical_payload}".encode()).hexdigest()
print(token)
```

## Configuration

Settings are defined in `app/core/config.py` and loaded from environment variables or `.env`.

Minimum practical local variables:

```env
SMARTREST_APP_ENV=local_acceptance
SMARTREST_AUTH_SECRET_KEY=...
SMARTREST_PLATFORM_ADMIN_SECRET_KEY=...
SMARTREST_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@smartrest_db:5432/smartrest
SMARTREST_CHAT_ANALYTICS_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@smartrest_db:5432/chat_analytics_db
SMARTREST_SCOPE_BACKEND_MODE=db_strict
SMARTREST_REPORT_BACKEND_MODE=db_strict
SMARTREST_ANALYTICS_BACKEND_MODE=db_strict
SMARTREST_PLANNER_MODE=hybrid
SMARTREST_OPENAI_API_KEY=...
TOON_LAHMAJO_DB=mysql+pymysql://root:pass@database:3306/toon_lahmajo
```

Use `.env.example` as the starting point.

### Configuration Notes

- Do not commit real secrets into `.env`.
- `SMARTREST_PLANNER_MODE=deterministic` is the safest mode for infrastructure bring-up because it removes the OpenAI requirement.
- `SMARTREST_PLANNER_MODE=hybrid` is the normal local mode when OpenAI-backed planning should be available.
- `SMARTREST_SCOPE_BACKEND_MODE`, `SMARTREST_REPORT_BACKEND_MODE`, and `SMARTREST_ANALYTICS_BACKEND_MODE` should normally remain `db_strict`.
- `SMARTREST_PLATFORM_ADMIN_BYPASS_SUBSCRIPTION=false` is the safer default. Only enable bypass intentionally for controlled internal testing.

### Host Run vs Docker Run

The sample values in `.env.example` are correct when the app runs inside Docker Compose.

If you run the app directly on the host with `.venv/bin/python -m uvicorn ...`, update the database URLs to the published host ports:

```env
SMARTREST_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@127.0.0.1:5433/smartrest
SMARTREST_CHAT_ANALYTICS_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@127.0.0.1:5433/chat_analytics_db
TOON_LAHMAJO_DB=mysql+pymysql://root:pass@127.0.0.1:35564/smartrest
```

If you run the app inside Docker Compose, keep the container hostnames:

```env
SMARTREST_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@smartrest_db:5432/smartrest
SMARTREST_CHAT_ANALYTICS_DATABASE_URL=postgresql+psycopg://smartrest:smartrest@smartrest_db:5432/chat_analytics_db
TOON_LAHMAJO_DB=mysql+pymysql://root:pass@database:3306/smartrest
```

### Runtime Environments

- `development`: relaxed local development
- `local_acceptance`: strict local validation
- `staging`: strict non-production environment
- `production`: strict runtime requirements

In non-development strict environments, the app validates:

- auth secret key presence
- operational DB URL presence
- chat analytics DB URL presence
- OpenAI API key when planner mode is not deterministic
- `db_strict` backend mode enforcement

## First-Time Bootstrap

Use this exact sequence on a fresh machine or fresh local checkout.

### 1. Create the environment file

```bash
cp .env.example .env
```

Then decide how the app will run:

- host Python process with Docker-backed databases
- full Docker Compose app + databases

Update the DB URLs in `.env` accordingly using the examples above.

### 2. Create the Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Start the local databases

Recommended minimum services:

```bash
docker compose --profile db up -d smartrest_db database
```

Optional DB UIs:

```bash
docker compose --profile db up -d adminer phpmyadmin
```

### 4. Run both migration tracks

```bash
make migrate-smartrest
make migrate-chat-analytics
```

### 5. Run sync flows

Identity sync should run before mapped-table sync:

```bash
make sync-toon-identities
make sync-toon-smartrest
```

For cautious or table-specific validation:

```bash
make sync-toon-smartrest-step table=profiles_room_table_order batch=500
```

### 6. Validate the environment

```bash
make test
make test-integration
make test-post-sync
```

Suggested validation order:

1. `make test` after dependencies and migrations are ready
2. `make test-integration` after chat analytics Postgres is reachable
3. `make test-post-sync` after the operational SmartRest sync is complete

### 7. Start the service

Host run:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Docker run:

```bash
docker compose up -d app
```

### 8. Confirm service health

Host-run app:

```bash
curl http://127.0.0.1:8000/health
```

Docker Compose app:

```bash
curl http://127.0.0.1:8001/health
```

## Local Setup

### Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Then start the service:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Make Targets

Useful commands from `Makefile`:

```bash
make setup
make run-8010
make lint
make typecheck
make test
make test-integration
make test-post-sync
make migrate-chat-analytics
make migrate-smartrest
make current-chat-analytics
make current-smartrest
make sync-toon-identities
make sync-toon-smartrest
make sync-toon-smartrest-step table=profiles_room_table_order batch=500
```

### Docker Compose

The repository includes:

- app service
- Postgres service for SmartRest and chat analytics
- Adminer
- MariaDB and phpMyAdmin for source-side local work

Start the full stack:

```bash
docker compose --profile db up --build
```

Start only databases:

```bash
docker compose --profile db up -d smartrest_db database
```

Start only the app:

```bash
docker compose up -d app
```

Useful Docker inspection commands:

```bash
docker compose logs -f --tail=200 app
docker compose logs -f --tail=200 smartrest_db
docker compose exec smartrest_db psql -U smartrest -d smartrest
docker compose exec smartrest_db psql -U smartrest -d chat_analytics_db -c "\dt"
```

## Database and Migrations

There are two Alembic tracks:

- `migrations/chat_analytics`
- `migrations/smartrest`

Migration commands:

```bash
make migrate-chat-analytics
make current-chat-analytics
make revision-chat-analytics m="your message"

make migrate-smartrest
make current-smartrest
make revision-smartrest m="your message"
```

Recommended operational order:

1. bring up Postgres
2. apply `smartrest` migrations
3. apply `chat_analytics` migrations
4. run sync flows
5. run validation tests
6. start the app

Notes:

- The local Postgres init script creates `chat_analytics_db` automatically in Docker.
- The operational schema and chat analytics schema are versioned independently and both must be current.

## Sync Pipeline

The sync layer is part of the current system, not a future placeholder.

Available flows:

- identity sync runner
- mapped-table SmartRest sync runner
- one-table stepping for large or risky sync passes

Commands:

```bash
make sync-toon-identities
make sync-toon-smartrest
make sync-toon-smartrest-step table=profiles_room_table_order batch=500
```

### Recommended Sync Order

Use this order unless you intentionally need a targeted recovery flow:

1. `make sync-toon-identities`
2. `make sync-toon-smartrest`
3. `make test-post-sync`

Why this order:

- identity sync prepares canonical mappings used by scope resolution and admin execution
- mapped-table sync loads operational SmartRest tables used by reports and live analytics
- post-sync tests verify that the runtime can safely use the synced DB

### When To Use Step Mode

Use `make sync-toon-smartrest-step ...` when:

- testing a single large or risky table
- recovering from a table-specific sync problem
- validating a mapping change
- inspecting cursor or batching behavior

### What “Ready” Looks Like After Sync

Treat the local environment as usable when all of the following are true:

- identity sync completes without critical unresolved mappings
- mapped-table sync completes for the required business tables
- `make test-post-sync` passes
- `/health` returns `ok`
- at least one known-good tenant request succeeds through `/agent/run`

## Tooling and Execution Model

The runtime uses a bounded internal tool registry. This is a core design choice.

Current tool groups include:

- scope resolution
- report execution
- total metric retrieval
- breakdown retrieval
- timeseries retrieval
- scalar metric calculations
- ranking
- moving average
- trend slope
- business insight tools for items, customers, and receipts

Business answers are expected to be grounded in these tools, not directly in model text generation.

## Usage Cookbook

This section is intended for later day-to-day use of the project.

### Build a Tenant Auth Token

```python
import hashlib
import time

secret = "your-secret"
current_timestamp = int(time.time())
profile_nick = "demo_profile"
profile_id = 201
user_id = 101

canonical_payload = f"{current_timestamp}-{profile_nick}-{profile_id}-{user_id}"
token = hashlib.sha256(f"{secret}-{canonical_payload}".encode()).hexdigest()
print(current_timestamp)
print(token)
```

### Run a Tenant Query with `curl`

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{
    "chat_id": "11111111-1111-1111-1111-111111111111",
    "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
    "auth": {
      "profile_nick": "demo_profile",
      "user_id": 101,
      "profile_id": 201,
      "current_timestamp": 1760000000,
      "token": "replace-with-real-token"
    },
    "scope_request": {
      "user_id": 101,
      "profile_id": 201,
      "profile_nick": "demo_profile",
      "metadata": {},
      "requested_branch_ids": null,
      "requested_export_mode": null
    }
  }'
```

Expected successful response patterns:

- `completed` for grounded successful runs
- `clarify` when the planner needs more detail
- `rejected` for unsupported requests
- `denied` for access or scope denial
- `onboarding` for greeting or smalltalk requests

### Restrict Branches or Export Mode in a Request

```json
{
  "scope_request": {
    "user_id": 101,
    "profile_id": 201,
    "profile_nick": "demo_profile",
    "metadata": {},
    "requested_branch_ids": ["branch_7", "branch_8"],
    "requested_export_mode": "csv"
  }
}
```

Use these fields only when the caller intentionally wants narrower execution context.

### Platform Admin Profile Listing

```bash
curl -X POST http://127.0.0.1:8000/agent/admin/profiles \
  -H 'Content-Type: application/json' \
  -d '{
    "admin_auth": {
      "admin_id": "owner",
      "current_timestamp": 1760000000,
      "token": "replace-with-real-admin-token"
    }
  }'
```

### Platform Admin Tenant Execution

```bash
curl -X POST http://127.0.0.1:8000/agent/admin/run \
  -H 'Content-Type: application/json' \
  -d '{
    "chat_id": "11111111-1111-1111-1111-111111111111",
    "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
    "admin_auth": {
      "admin_id": "owner",
      "current_timestamp": 1760000000,
      "token": "replace-with-real-admin-token"
    },
    "target_profile_id": 201,
    "target_profile_nick": "demo_profile",
    "target_user_id": 101,
    "metadata": {},
    "requested_branch_ids": null,
    "requested_export_mode": null
  }'
```

### Typical Questions This Agent Should Handle

- `What were total sales 2026-03-01 to 2026-03-07?`
- `How many orders did we have last week?`
- `Show sales by source 2026-03-01 to 2026-03-07`
- `Compare sales this week vs previous week`
- `Which items performed best this month?`
- `Show the sales trend for the last 30 days`

### Typical Questions This Agent Should Not Be Used For

- open-ended general knowledge
- free-form database exploration
- arbitrary SQL generation
- unsupported SmartRest metrics or dimensions not backed by the runtime
- any question where the caller expects the model itself to invent business truth

## Daily Operations

Typical later-use workflow:

1. confirm `.env` still matches the chosen runtime mode
2. start databases if they are not already running
3. apply pending migrations if the branch changed
4. run sync flows when source data or mappings changed
5. run `make test` and the relevant DB-backed tests
6. start the service and confirm `/health`
7. test one known-good tenant request before broader use

Recommended known-good smoke checks:

- `GET /health`
- one tenant `POST /agent/run`
- one platform-admin profile listing
- one query that should clarify
- one query that should reject

## Testing

Quality gates:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy app
.venv/bin/python -m pytest
```

Pytest markers:

- `integration`: tests that require local Postgres-backed infrastructure
- `post_sync`: smoke checks intended for use after local SmartRest sync completes

Examples:

```bash
.venv/bin/python -m pytest -m integration
.venv/bin/python -m pytest -m post_sync
```

### Test Selection Guidance

- Run `make test` for fast repository-wide validation.
- Run `make test-integration` when chat analytics DB behavior or persistence changes.
- Run `make test-post-sync` after sync operations or operational DB changes.
- Run `make test-all` only when you explicitly want all tiers together.

### Important Test Policy

- Skip markers are intentionally disallowed by repository policy.
- Integration tests require a reachable chat analytics Postgres database.
- Post-sync tests require a reachable operational SmartRest/Postgres database.

## Current Strengths

- clear architecture boundaries
- typed request, state, and tool contracts
- bounded tool model instead of uncontrolled agent behavior
- real DB-backed reporting and analytics already present
- runtime persistence already wired
- broad automated test coverage
- strict runtime configuration checks

## Current Risks and Known Gaps

These are the important current limitations:

- permission-bearing context is still influenced by request metadata in places
- live analytics coverage is broader than before but not yet complete across all advanced paths
- end-to-end strict live API coverage should be expanded
- `app/agent/graph.py` is large and should eventually be modularized

The service should therefore be treated as a serious local/internal engineering system with a clear path to production hardening, not as a finished production deployment.

## Troubleshooting

### `/health` does not return `ok`

Check:

- the app process is running
- the chosen port is correct
- startup did not fail on strict runtime validation

Common causes:

- missing auth secret
- missing DB URLs
- missing OpenAI key when planner mode is not deterministic

### `401 Unauthorized`

Check:

- secret key matches the caller
- token was built from the exact canonical payload
- `current_timestamp` is within the allowed age/skew window
- `profile_nick`, `profile_id`, and `user_id` exactly match the signed values

### `403 Forbidden`

Likely causes:

- subscription is inactive
- target tenant is not allowed
- requested branch or export mode is outside allowed scope

### Runtime returns `denied`

Check:

- identity sync has been run
- canonical profile and user mappings exist
- the SmartRest operational DB is reachable

If canonical identity mapping is missing, rerun:

```bash
make sync-toon-identities
```

### Report or analytics answers look incomplete

Check:

- whether the request hit a known unsupported metric or dimension
- whether warnings were returned in the response
- whether the synced operational DB actually contains the source data needed for that question

### `planner_*_fallback` warnings appear

This means the runtime degraded from LLM-backed planning to deterministic planning.

Check:

- OpenAI API key presence
- planner mode in `.env`
- runtime network reachability for the OpenAI call path

### Persistence warnings appear

Typical meanings:

- `persistence_unavailable`: chat analytics DB unreachable or failed
- `persistence_missing_context`: run start did not create persistence context
- `persistence_invalid_identity` or `persistence_invalid_input`: invalid persistence payload

Check:

- chat analytics DB URL
- chat analytics migrations
- DB connectivity

### `make test-integration` or `make test-post-sync` fails immediately

This usually means the required DB URL is missing or the database is not reachable.

Check:

- `SMARTREST_CHAT_ANALYTICS_DATABASE_URL` for integration tests
- `SMARTREST_DATABASE_URL` for post-sync tests
- active Docker containers and exposed ports

## Production Cautions

This repository is production-shaped but not fully production-hardened.

Before treating it as a production deployment, review at minimum:

- trust-boundary hardening for scope and permission behavior
- broader live analytics coverage
- real end-to-end validation with production-like infrastructure
- observability and incident-debugging requirements
- rollout and rollback procedures outside local development

## Repository Documentation Policy

This `README.md` is the main operational entry point.

Use these documents alongside it:

- `SmartRest_Agent_Logic_Guide.md`: architecture and runtime explanation
- `TODO.md`: active execution roadmap
- `recommendations.md`: engineering recommendations and cleanup notes
- `afterwards.md`: post-sync hardening roadmap
- `codex_prompt.md`: local collaboration rules for code-assistant work

Older duplicated planning docs were removed to keep the repository documentation set authoritative.
