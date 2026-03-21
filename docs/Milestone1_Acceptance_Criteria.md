# Milestone 1 Acceptance Criteria

Date: 2026-03-10  
Status: approved baseline checklist for Milestone 1

## 1) Scope of This Checklist
This document defines objective pass/fail criteria for Milestone 1:
- first runnable LangGraph agent loop
- tool-first business answer policy
- controlled clarify/reject behavior
- persistence and testability foundations

## 2) Milestone 1 Definition
Milestone 1 is complete only if all `mandatory` gates pass.

## 3) Mandatory Gates (Pass/Fail)

### M1-F1 Functional Flow
Requirement:
- Agent executes this workflow end-to-end for supported requests:
  - `resolve_scope -> plan_analysis -> policy_gate -> route_decision`
  - `prepare_legacy_report -> run_report -> calc_metrics -> compose_answer`
Pass condition:
- Integration test confirms all required nodes execute in order.

### M1-F2 Clarification Flow
Requirement:
- Missing or ambiguous time filter routes to clarification.
Pass condition:
- Test case with missing time filter returns clarification response and does not run report tool.

### M1-F3 Unsupported Flow
Requirement:
- Unsupported requests are rejected cleanly with supported alternatives.
Pass condition:
- Test case for unsupported request returns reject status and no report execution.

### M1-F5 Onboarding Flow
Requirement:
- Greeting/casual non-business requests route to onboarding response.
Pass condition:
- Test case for smalltalk returns `status=onboarding`, with
  `needs_clarification=false` and `clarification_question=null`.

### M1-F4 Scope Enforcement
Requirement:
- Scope must be resolved before report execution.
Pass condition:
- If scope is denied/unresolved, run_report is not called and response is safe deny.

### M1-S1 Tool-Truth Safety
Requirement:
- Business numbers in final answer must come from tool outputs only.
Pass condition:
- Tests verify response values map to tool output payload and are not LLM-invented.

### M1-S2 OpenAI Guardrails
Requirement:
- OpenAI is used only for interpretation and answer composition.
Pass condition:
- No SQL generation path exists in code and no direct KPI computation in LLM layer.

### M1-P1 Persistence
Requirement:
- Run metadata and state checkpoints are persisted for each execution.
Pass condition:
- Test confirms run/thread identifiers and at least one persisted state transition.

### M1-Q1 API Boundary Integrity
Requirement:
- API layer validates input and calls runtime only; no orchestration/business routing in route handlers.
Pass condition:
- API tests pass and route code contains no graph decision logic.

### M1-Q2 Quality Gates
Requirement:
- Baseline quality commands pass.
Pass condition:
- `ruff check .` passes.
- `mypy app` passes.
- `pytest` passes.

### M1-O1 Output Contract
Requirement:
- Response contains:
  - answer
  - applied filters
  - warnings/limitations/status when relevant
Pass condition:
- Response schema and integration tests validate all required output fields.

### M1-R1 Reproducibility
Requirement:
- Test suite runs without real database dependency.
Pass condition:
- Mock backend is used in tests and CI-local run.

## 4) Test Scenario Matrix (Minimum)
- `T1_supported_query_executes_full_run`
- `T2_missing_time_requires_clarification`
- `T3_unsupported_request_rejected`
- `T4_scope_denied_blocks_report_execution`
- `T5_tool_output_is_source_of_numbers`
- `T6_output_contract_fields_present`
- `T7_persistence_records_run_and_state`
- `T8_quality_gate_commands_pass`
- `T9_smalltalk_returns_onboarding_contract`

## 5) Completion Rule
Milestone 1 can be marked done only when:
- all mandatory gates (`M1-*`) are passing
- scenario matrix tests pass
- no open blocker remains for scope, architecture, or acceptance baseline
