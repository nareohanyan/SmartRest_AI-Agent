# SmartRest Agent Logic Guide

This document explains how the project works today.

Use it as the technical narrative for the repository:

- what the system is
- how requests move through it
- where business truth comes from
- how the data layer fits in
- what is already solid
- what still needs hardening

## 1. What This Project Is

SmartRest AI Agent is a bounded business analytics service for SmartRest data.

It is not a generic chatbot and it is not an open-ended database agent.

Its job is to:

1. accept a signed SmartRest request
2. verify identity and subscription access
3. resolve execution scope
4. interpret the business question into a typed plan
5. execute approved report or analytics tools
6. compose a grounded answer
7. persist runtime artifacts for inspection

The system is designed to answer business questions such as:

- total sales in a time window
- order count and average check
- comparisons versus a previous period
- rankings and breakdowns
- trends over time
- selected business insight queries backed by trusted tools

## 2. Core Design Position

The project is intentionally constrained.

The model is allowed to help with interpretation and response phrasing, but it is not the source of business truth. Business numbers must come from tools and database-backed retrieval.

That design choice drives the whole architecture:

- FastAPI is the transport boundary
- LangGraph owns orchestration
- typed schemas define contracts
- tools are explicit and bounded
- SmartRest-backed services provide the data
- persistence records what happened

## 3. High-Level Architecture

```text
Client
  |
  v
FastAPI API Layer
  |
  v
Auth + Subscription Gate
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
  |         +--> Tool Registry
  |                |
  |                +--> scope resolution
  |                +--> report execution
  |                +--> analytics retrieval
  |                +--> ranking / trend / calculations
  |
  +--> SmartRest operational database
      Chat analytics database
      Sync pipeline inputs
```

## 4. Main Runtime Components

### API Layer

The API surface lives under `app/api`.

Responsibilities:

- receive and validate request payloads
- verify signed tenant or platform-admin auth
- check subscription access
- call the runtime service
- return the final contract

Non-responsibilities:

- no graph routing logic
- no KPI calculation
- no direct database querying from route handlers

### Runtime Service

`app/services/agent_runtime.py` is the execution boundary between the API and the graph.

Responsibilities:

- build the initial typed state
- start and finish runtime persistence
- invoke the graph
- normalize the final API response
- classify runtime failures

### LangGraph Workflow

`app/agent/graph.py` contains the orchestration logic.

Current graph responsibilities include:

- scope resolution
- planning
- policy gating
- route selection
- report execution
- comparison / ranking / trend execution
- business insight execution
- clarification / rejection / smalltalk handling
- answer composition

The graph already carries structured state and execution trace data. It is functional, but it is also one of the largest files in the repository and is a clear future refactor target.

### Tool Layer

The tool layer is deliberately bounded. The registry in `app/agent/tool_registry.py` defines which operations exist and what request types they accept.

Current tool families include:

- scope and report tools
- total / breakdown / timeseries retrieval
- scalar metric calculations
- ranking tools
- moving average and trend slope tools
- business insight tools for items, customers, and receipts

This keeps the system inspectable and prevents uncontrolled tool growth.

### Data and Backend Layer

The repository is no longer purely mock-backed.

There are real SmartRest-backed implementations for:

- canonical identity resolution
- scope resolution
- core report execution
- live analytics retrieval
- post-sync smoke validation

The system is still hybrid in capability coverage, not in architecture. Some paths are fully grounded, while some advanced paths still need deeper live-data coverage and stricter trust-boundary handling.

### Persistence Layer

Runtime persistence writes execution metadata to the chat analytics database.

The persistence layer supports:

- run lifecycle tracking
- status mapping
- message and answer recording
- warnings around persistence behavior

This gives the project operational memory without pushing orchestration concerns into the API.

## 5. Request Lifecycle

The normal tenant flow is:

1. client sends `/agent/run`
2. signed payload is verified
3. subscription access is checked
4. runtime service starts a run record
5. LangGraph receives the initial `AgentState`
6. scope is resolved
7. planning determines the intent and route
8. policy gate validates the requested operation
9. the graph executes one of the approved branches
10. answer composition produces a grounded response
11. runtime service finalizes persistence and returns the API contract

Platform-admin execution uses a parallel flow through `/agent/admin/run`, but target identity is resolved first and can optionally bypass subscription checks depending on environment settings.

## 6. Current Graph Branches

The graph currently supports these broad outcomes:

- `completed`
- `clarify`
- `rejected`
- `denied`
- `failed`
- `onboarding`

Operationally, the graph can execute:

- legacy report path
- multi-report path
- comparison path
- ranking path
- trend path
- business insight path
- safe-answer path
- clarification path
- rejection path
- smalltalk path

This means the project is already beyond the initial report-only baseline.

## 7. State Model

`app/schemas/agent.py` defines the shared run state.

Important state groups include:

- request identity and question
- resolved scope
- selected intent and plan
- selected report and filters
- tool responses
- analysis artifacts
- execution trace
- base and derived metrics
- warnings
- final answer and run status

This is one of the strongest parts of the codebase: the runtime is not a pile of ad hoc dictionaries and disconnected service calls.

## 8. Data Truth Policy

Business truth should come from:

- report tool outputs
- analytics retrieval outputs
- deterministic calculation outputs

The model may:

- classify intent
- help interpret the question
- help phrase the final answer

The model must not:

- invent KPI values
- bypass tools
- fabricate report outputs
- act as the source of business truth

## 9. Authentication and Access

The service currently enforces:

- signed request verification
- subscription access checks
- canonical identity resolution
- policy gating before execution
- strict runtime configuration in non-development environments

This is a meaningful strength, but one major issue remains:

client-provided metadata still influences parts of scope and permission shaping. That is acceptable for local development and controlled use, but it is not the final trust-boundary design for production.

In practical terms, the next hardening step is to move permission-bearing context fully to trusted server-side resolution.

## 10. Runtime Modes and Configuration

The project uses typed settings from `app/core/config.py`.

Important current characteristics:

- `development`, `local_acceptance`, `staging`, and `production` environments exist
- strict environments enforce required secrets and database URLs
- strict environments require `db_strict` backend modes
- planner mode can be deterministic, hybrid, or llm

This is materially stronger than the old documentation suggested. The repository already has fail-fast runtime policy checks.

## 11. Databases and Sync

There are two main database concerns in the repo:

### SmartRest operational database

Used for:

- canonical identity resolution
- report execution
- analytics retrieval
- post-sync validation

### Chat analytics database

Used for:

- runtime persistence
- analytics around conversations and execution lifecycle

### Sync pipeline

The repo includes a real sync path for:

- identity synchronization
- mapped-table synchronization
- SmartRest schema migrations and seeded mapping batches

This is important because the agent is not operating on imaginary future data infrastructure anymore. The data pipeline is already part of the system.

## 12. Testing Model

The test suite is broad and is one of the strongest indicators of project maturity.

It covers:

- API contracts
- auth logic
- planner and parser logic
- policy decisions
- graph behavior
- runtime persistence
- report tools
- live-backend behavior
- migration behavior
- post-sync smoke checks

There are also explicit `integration` and `post_sync` markers, which gives the repo a reasonable base for separating lightweight checks from DB-backed validation.

## 13. What Is Already Strong

The strongest parts of the repository are:

- clear layering
- typed contracts
- bounded tool model
- graph-based orchestration
- strong test coverage
- real DB integration already present
- runtime persistence already wired
- strict-environment configuration checks

This is not a toy prototype anymore. It is a structured backend system with real runtime shape.

## 14. What Is Still Weak

The main weaknesses are not about missing architecture. They are about trust, completeness, and operability.

### Trust boundary still needs hardening

Some request metadata still influences effective scope behavior. That should be tightened before calling the system production-safe.

### Live analytics coverage is incomplete

Some advanced analytics paths still have narrower live-data support than the planner and graph structure suggest.

### Documentation drift existed

Several older docs described a pre-integration state that no longer matched the codebase. This guide is intended to replace that confusion with one current explanation.

### Graph complexity is concentrated

`app/agent/graph.py` is effective but too large. It works, but it should eventually be modularized to reduce change risk.

### End-to-end strict live API coverage should grow

The test suite is broad, but the public API should have more DB-backed integration scenarios beyond mocked unit-style coverage.

## 15. Working Rules for This Project

1. Keep business truth in tools and data services, not in prompts.
2. Keep orchestration in the graph, not in route handlers.
3. Keep contracts typed and explicit.
4. Keep tools bounded and registry-driven.
5. Prefer controlled failures over fake business data.
6. Treat sync correctness as part of runtime trust, not just ETL success.
7. Do not let documentation describe a system that no longer exists.

## 16. Short Version

If everything starts feeling noisy, remember this:

SmartRest AI Agent is a FastAPI + LangGraph analytics service that verifies identity, resolves scope, plans a bounded analysis, executes approved SmartRest-backed tools, composes a grounded answer, and persists the run.

That is the real shape of the project today.
