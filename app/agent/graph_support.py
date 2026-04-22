from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from app.agent.llm import LLMClientError, build_response_messages
from app.agent.response_text import _question_language
from app.schemas.agent import (
    AgentState,
    ExecutionStepStatus,
    ExecutionTraceStep,
    IntentType,
)
from app.schemas.analysis import AnalysisIntent, RetrievalScope, ToolWarningCode


def _parse_branch_id(raw_branch_id: str) -> int | None:
    normalized = raw_branch_id.strip()
    if normalized.startswith("branch_"):
        normalized = normalized[len("branch_") :]
    try:
        return int(normalized)
    except ValueError:
        return None


def _normalize_branch_ids(raw_branch_ids: list[str] | None) -> list[int]:
    if not raw_branch_ids:
        return []

    branch_ids: list[int] = []
    seen: set[int] = set()
    for raw_branch_id in raw_branch_ids:
        parsed = _parse_branch_id(raw_branch_id)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        branch_ids.append(parsed)
    return branch_ids


def _scoped_branch_ids(state: AgentState) -> list[int]:
    requested_branch_ids = (
        state.scope_request.requested_branch_ids
        if state.scope_request is not None
        else None
    )
    if requested_branch_ids:
        return _normalize_branch_ids(requested_branch_ids)

    scope = state.user_scope
    if scope is None:
        return []

    allowed_branch_ids = scope.allowed_branch_ids or []
    if "*" in allowed_branch_ids:
        return []
    return _normalize_branch_ids(allowed_branch_ids)


def _build_retrieval_scope(state: AgentState) -> RetrievalScope | None:
    if state.scope_request is None:
        return None

    source = None
    if state.filters is not None:
        source = state.filters.source

    return RetrievalScope(
        profile_id=state.scope_request.profile_id,
        branch_ids=_scoped_branch_ids(state),
        source=source,
    )


def _map_analysis_intent_to_runtime_intent(analysis_intent: AnalysisIntent) -> IntentType:
    if analysis_intent in {AnalysisIntent.BREAKDOWN, AnalysisIntent.RANKING}:
        return IntentType.BREAKDOWN_KPI
    if analysis_intent is AnalysisIntent.SMALLTALK:
        return IntentType.SMALLTALK
    if analysis_intent is AnalysisIntent.CLARIFY:
        return IntentType.NEEDS_CLARIFICATION
    if analysis_intent is AnalysisIntent.UNSUPPORTED:
        return IntentType.UNSUPPORTED_REQUEST
    return IntentType.GET_KPI


def _render_answer_with_llm(
    *,
    state: AgentState,
    route: str,
    fallback_answer: str,
    settings_loader: Callable[[], Any],
    llm_client_factory: Callable[[], Any],
) -> tuple[str, list[str]]:
    settings = settings_loader()
    api_key = getattr(settings, "openai_api_key", None)
    if api_key is None or not str(api_key).strip():
        return fallback_answer, state.warnings

    try:
        llm_client = llm_client_factory()
        messages = build_response_messages(
            {
                "route": route,
                "answer_kind": state.analysis_artifacts.get("kind"),
                "language_hint": _question_language(state.user_question),
                "user_question": state.user_question,
                "factual_answer": fallback_answer,
                "policy_reason": state.policy_reason,
                "warnings": state.warnings,
            }
        )
        rendered = llm_client.generate_text(messages=messages).strip()
        if not rendered:
            raise ValueError("LLM response rendering returned empty text.")
        return rendered, state.warnings
    except (LLMClientError, ValueError):
        return fallback_answer, [*state.warnings, "response_llm_fallback"]


def _merge_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning in seen:
                continue
            seen.add(warning)
            merged.append(warning)
    return merged


def _stringify_tool_warnings(warnings: list[ToolWarningCode]) -> list[str]:
    return [f"tool:{warning.value}" for warning in warnings]


def _append_tool_trace_step(
    trace: list[ExecutionTraceStep],
    *,
    step_id: str,
    input_ref: str,
    output_ref: str,
    started_at: float,
    status: ExecutionStepStatus = ExecutionStepStatus.SUCCESS,
    warnings: list[str] | None = None,
    error_code: str | None = None,
) -> list[ExecutionTraceStep]:
    return [
        *trace,
        ExecutionTraceStep(
            step_id=step_id,
            status=status,
            input_ref=input_ref,
            output_ref=output_ref,
            duration_ms=(perf_counter() - started_at) * 1000,
            warnings=warnings or [],
            error_code=error_code,
        ),
    ]
