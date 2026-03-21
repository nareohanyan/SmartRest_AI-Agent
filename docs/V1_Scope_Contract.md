# SmartRest Agent V1 Scope Contract

Date: 2026-03-10
Status: approved baseline for V1 implementation

## In Scope (V1)
- Single-turn reporting questions only.
- Intent types:
  - `get_kpi`
  - `breakdown_kpi`
  - `smalltalk`
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
  - `resolve_scope -> plan_analysis -> policy_gate -> route_decision`
  - `prepare_legacy_report -> run_report -> calc_metrics -> compose_answer`
  - `run_comparison|run_ranking|run_trend -> compose_answer`
  - `onboarding|clarify|reject` as terminal branches
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
- Greeting/casual non-business request -> onboarding response.
  - status: `onboarding`
  - needs_clarification: `false`
  - clarification_question: `null`
- Missing or ambiguous time filter -> ask clarification, do not guess.
- Unsupported request -> explicit rejection with supported alternatives.
- Scope unresolved or forbidden -> safe deny response.
- No orchestration logic in API routes.
- LLM may interpret and compose; tool outputs are the source of business truth.
