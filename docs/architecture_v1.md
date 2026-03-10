# SmartRest Agent Architecture V1

Date: 2026-03-10  
Status: approved baseline for V1 implementation

## 1) Purpose
Define the implementation blueprint for V1 so the team builds a consistent, testable, tool-first reporting agent.

## 2) Design Principles
- Tool outputs are the source of business truth.
- LangGraph owns orchestration.
- API is a transport boundary, not a business logic layer.
- OpenAI is used for interpretation and answer composition only.
- Backend implementation is replaceable.

## 3) High-Level Architecture

```text
Client
  |
  v
FastAPI API Layer
  |
  v
LangGraph Agent Runtime
  |            |               |
  |            |               +--> Persistence Layer (run/thread/state checkpoints)
  |            |
  |            +--> OpenAI Layer (interpret + compose)
  |
  +--> Tool Layer (resolve_scope, list_reports, get_report_definition, run_report)
                  |
                  v
            Backend/Data Provider Layer
            (mock now, SmartRest DB adapter later)
```

## 4) System Layers and Boundaries

### 4.1 FastAPI API Layer
Responsibilities:
- Receive request.
- Validate payload.
- Create request metadata.
- Call agent runtime and return response.

Non-responsibilities:
- No routing decisions.
- No report selection logic.
- No business KPI calculations.

### 4.2 LangGraph Agent Runtime
Responsibilities:
- Hold and transition shared agent state.
- Execute node workflow.
- Route to run/clarify/reject branches.

Non-responsibilities:
- No direct data retrieval bypassing tools.
- No direct DB coupling.

### 4.3 OpenAI Interpretation and Composition Layer
Responsibilities:
- Interpret user request into structured intent/filters/report candidate.
- Compose user-facing answer from tool outputs.

Non-responsibilities:
- No KPI computation.
- No business-number generation without tools.
- No SQL generation in V1.

### 4.4 Tool Layer
Responsibilities:
- Provide deterministic, typed operations for scope and reporting.
- Enforce input/output contracts.

Non-responsibilities:
- No orchestration flow decisions.

### 4.5 Backend/Data Provider Layer
Responsibilities:
- Execute data retrieval for report tools.
- Provide mock data now and DB-backed implementation later.

Non-responsibilities:
- No agent flow/state handling.

### 4.6 Persistence Layer
Responsibilities:
- Persist run/thread identifiers and state checkpoints.
- Support replay/inspection of runs.

Non-responsibilities:
- No business logic.

## 5) Official V1 Workflow

```text
resolve_scope
  -> interpret_request
  -> route_decision
     -> run_report -> compose_answer
     -> clarify
     -> reject
```

Node-by-node behavior:
- `resolve_scope`: identify user scope and allowed reports.
- `interpret_request`: extract intent, report_id candidate, and filters.
- `route_decision`: branch to run, clarify, or reject.
- `run_report`: execute report tool with validated filters.
- `clarify`: return missing-information prompt.
- `reject`: return unsupported-request response and alternatives.
- `compose_answer`: produce final response from tool outputs and context.

## 6) Shared Agent State (V1)

Required state fields:
- `thread_id`: conversation thread identifier.
- `run_id`: unique execution identifier.
- `user_question`: raw user message.
- `user_scope`: resolved access scope/permissions.
- `intent`: interpreted intent (`get_kpi`, `breakdown_kpi`, `needs_clarification`, `unsupported_request`).
- `selected_report_id`: chosen report ID if supported.
- `filters`: normalized report filters.
- `needs_clarification`: boolean.
- `clarification_question`: question to ask when information is missing.
- `tool_outputs`: outputs collected from tool calls.
- `warnings`: limitations/warnings for response.
- `final_answer`: response content returned to user.
- `status`: run status (for example `running`, `completed`, `clarify`, `rejected`, `denied`, `failed`).

## 7) V1 Tools

- `resolve_scope_tool`
  - Input: user identity/context metadata.
  - Output: allowed scope, allowed report IDs, access status.

- `list_reports_tool`
  - Input: scope context.
  - Output: list of supported report IDs and brief descriptions.

- `get_report_definition_tool`
  - Input: report ID.
  - Output: required/optional filters and report metadata.

- `run_report_tool`
  - Input: report ID + validated filters + scope.
  - Output: deterministic report result payload.

Supported report IDs in V1:
- `sales_total`
- `order_count`
- `average_check`
- `sales_by_source`

## 8) OpenAI Allowed vs Not Allowed (V1)

Allowed:
- Intent classification.
- Filter extraction and normalization hints.
- Clarification question drafting.
- Final answer composition from tool outputs.

Not allowed:
- Direct KPI calculation.
- Business-number fabrication.
- SQL generation.
- Report execution bypassing tools.

## 9) Failure Handling

- Missing or ambiguous time filter:
  - route to `clarify`.
- Unsupported question/report:
  - route to `reject` with supported alternatives.
- Scope unresolved or forbidden:
  - deny safely; do not execute report tools.
- Tool execution failure:
  - return controlled failure with warning; keep error details internal.

## 10) Integration Strategy

Current backend:
- Mock/prototype provider behind tool contracts.

Future backend:
- Replace backend provider with SmartRest DB adapter.
- Keep API, graph, state, and tool contracts stable.

This preserves architecture while changing only data implementation.
