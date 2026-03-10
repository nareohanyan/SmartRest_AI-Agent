# SmartRest Agent V1 Scope Contract

Date: 2026-03-10
Status: approved baseline for V1 implementation

## In Scope (V1)
- Single-turn reporting questions only.
- Intent types:
  - `get_kpi`
  - `breakdown_kpi`
  - `needs_clarification`
  - `unsupported_request`
- Supported report IDs:
  - `sales_total`
  - `order_count`
  - `average_check`
  - `sales_by_source`
- Time range is mandatory for supported report requests.
  - If missing or ambiguous, the agent must ask clarification.
- Source/channel filter is optional.
  - Only valid for source-aware reports (for example `sales_by_source` and source-filtered KPI requests).
- Agent flow:
  - `resolve_scope -> interpret_request -> route_decision -> run_report | clarify | reject -> compose_answer`
- Data policy:
  - Business numbers must come from tools only.
  - The LLM must not calculate KPIs directly.
- Output contract:
  - Answer
  - Applied filters
  - Warnings/limitations/status when relevant

## Out of Scope (V1)
- Real SmartRest DB connection.
- NL-to-SQL / semantic SQL generation.
- Multi-turn planning memory.
- Advanced anomaly/explanation nodes.
- Complex approval workflows.
- Production hardening beyond basic local reliability.
- Inventory, payroll, loyalty, and fiscal analytics.
- Any write operation.

## Behavior Rules (V1)
- Missing or ambiguous time filter -> ask clarification, do not guess.
- Unsupported request -> explicit rejection with supported alternatives.
- Scope unresolved or forbidden -> safe deny response.
- No orchestration logic in API routes.
- LLM may interpret and compose; tool outputs are the source of business truth.
