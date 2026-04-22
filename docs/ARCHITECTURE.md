# Architecture Guide

Last updated: 2026-04-22

## System Intent

SmartRest AI Agent is a bounded analytics service. The system is designed so that:

- the model helps with interpretation and wording
- the databases and tools provide business truth
- schemas and policies constrain what the system is allowed to do

This is intentionally not a generic agent and not an unconstrained NL-to-SQL engine.

## High-Level Flow

```text
User request
  ->
FastAPI API layer
  ->
auth + subscription checks
  ->
runtime service
  ->
LangGraph workflow
  ->
planning / policy / tools
  ->
grounded result
  ->
response rendering
  ->
runtime persistence
  ->
API response
```

## Major Layers

## 1. API Layer

Primary files:

- [app/main.py](../app/main.py)
- [app/api/app.py](../app/api/app.py)
- [app/api/schemas.py](../app/api/schemas.py)

Responsibilities:

- expose health and agent endpoints
- validate request/response contracts
- attach auth and runtime entrypoints

## 2. Core Runtime And Access Layer

Primary files:

- [app/core/auth.py](../app/core/auth.py)
- [app/core/config.py](../app/core/config.py)
- [app/core/runtime_policy.py](../app/core/runtime_policy.py)
- [app/services/subscription_access.py](../app/services/subscription_access.py)
- [app/services/platform_admin.py](../app/services/platform_admin.py)

Responsibilities:

- verify signed requests
- enforce runtime configuration rules
- resolve subscription access
- handle admin-mode execution

## 3. Runtime Orchestration Layer

Primary files:

- [app/services/agent_runtime.py](../app/services/agent_runtime.py)
- [app/agent/graph.py](../app/agent/graph.py)
- [app/schemas/agent.py](../app/schemas/agent.py)

Responsibilities:

- create and manage shared execution state
- drive the LangGraph workflow
- collect warnings, status, tool outputs, and selected reports
- coordinate persistence lifecycle

## 4. Planning And Parsing Layer

Primary files:

- [app/agent/planning.py](../app/agent/planning.py)
- [app/agent/parser_concepts.py](../app/agent/parser_concepts.py)
- [app/agent/parser_normalization.py](../app/agent/parser_normalization.py)
- [app/agent/parser_numbers.py](../app/agent/parser_numbers.py)
- [app/agent/planner_constraints.py](../app/agent/planner_constraints.py)
- [app/agent/planning_policy.py](../app/agent/planning_policy.py)

Responsibilities:

- normalize user wording
- detect supported intents
- map natural language to bounded query specs
- decide whether a route is allowed, unsupported, or needs clarification

Important design note:

This layer is intentionally conservative. Missing a colloquial phrasing is usually considered
safer than incorrectly routing a business question to the wrong metric or tool.

## 5. Tooling And Analytics Layer

Primary files:

- [app/agent/tools.py](../app/agent/tools.py)
- [app/agent/tool_registry.py](../app/agent/tool_registry.py)
- [app/agent/report_tools.py](../app/agent/report_tools.py)
- [app/agent/calc_tools.py](../app/agent/calc_tools.py)
- [app/agent/live_capabilities.py](../app/agent/live_capabilities.py)

Service-side business retrieval:

- [app/agent/services/live_business_tools.py](../app/agent/services/live_business_tools.py)
- [app/reports/smartrest_backend.py](../app/reports/smartrest_backend.py)

Responsibilities:

- expose bounded tool interfaces to the graph
- execute report and analytics retrieval
- compute rankings, comparisons, trends, and selected derived metrics
- explicitly block unsupported live capabilities

## 6. Response Layer

Primary files:

- [app/agent/response_text.py](../app/agent/response_text.py)
- [app/agent/graph_support.py](../app/agent/graph_support.py)
- [app/agent/llm/response.py](../app/agent/llm/response.py)

Responsibilities:

- produce deterministic fallback/business text
- localize labels and answer phrasing
- optionally let the LLM improve fluency while preserving grounded facts

Important design note:

This layer should improve wording, not invent new facts or reinterpret structured results.

## 7. Persistence Layer

Primary files:

- [app/persistence/runtime_persistence.py](../app/persistence/runtime_persistence.py)
- [app/persistence/chat_analytics_repository.py](../app/persistence/chat_analytics_repository.py)
- [app/persistence/status_mapper.py](../app/persistence/status_mapper.py)

Responsibilities:

- create run records
- write runtime messages and terminal statuses
- preserve traceability for agent execution

## 8. Data Layer

Primary files:

- [app/db/operational.py](../app/db/operational.py)
- [app/db/analytics.py](../app/db/analytics.py)
- [app/db/source.py](../app/db/source.py)
- [app/smartrest/models.py](../app/smartrest/models.py)
- [app/chat_analytics/models.py](../app/chat_analytics/models.py)

Responsibilities:

- operational SmartRest storage
- chat analytics storage
- source-side DB access for sync

## Key Architectural Rules

## Business Truth Rule

Business numbers must come from tools and databases, not model invention.

## Bounded Capability Rule

If a metric, dimension, ranking, or trend is not supported, the system should reject or
clarify rather than fake coverage.

## Layer Ownership Rule

Use this mental model when debugging:

- wrong intent parsing: planning layer
- wrong data result: tool/service/query layer
- wrong permission behavior: auth/scope/subscription layer
- awkward wording but correct facts: response layer

## Current Architectural Tensions

These are the main places where design clarity still needs work:

- deterministic parsing versus broader semantic flexibility
- hardcoded language/content behavior versus config-driven language behavior
- request metadata-driven scope versus server-trusted scope state
- async API surface versus mostly sync runtime internals

## Suggested Future Direction

The safest evolution path is:

1. keep execution and policy strongly typed and bounded
2. improve semantic normalization before widening execution freedom
3. move content and synonym surfaces toward configuration
4. harden trust boundaries before expanding planner autonomy
