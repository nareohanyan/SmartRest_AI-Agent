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
make test-post-sync
make migrate-chat-analytics
make migrate-smartrest
make sync-toon-identities
make sync-toon-smartrest
```

### Docker Compose

The repository includes:

- app service
- Postgres service for SmartRest and chat analytics
- Adminer
- MariaDB and phpMyAdmin for source-side local work

Start the stack:

```bash
docker compose --profile db up --build
```

Start only the app:

```bash
docker compose up -d app
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

## Repository Documentation Policy

This `README.md` is the main operational entry point.

Use these documents alongside it:

- `SmartRest_Agent_Logic_Guide.md`: architecture and runtime explanation
- `TODO.md`: active execution roadmap
- `recommendations.md`: engineering recommendations and cleanup notes
- `afterwards.md`: post-sync hardening roadmap
- `codex_prompt.md`: local collaboration rules for code-assistant work

Older duplicated planning docs were removed to keep the repository documentation set authoritative.
