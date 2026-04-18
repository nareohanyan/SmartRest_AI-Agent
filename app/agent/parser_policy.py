from __future__ import annotations

from app.agent.parser_structures import ParsedQuestion, ParserPolicyAction, ParserPolicyDecision


def decide_policy(parsed: ParsedQuestion) -> ParserPolicyDecision:
    if parsed.date_range is None:
        if parsed.wants_comparison:
            return ParserPolicyDecision(
                action=ParserPolicyAction.CLARIFY,
                clarification_question=_clarification_question(parsed.language),
                reasoning_notes="Comparison requests require an explicit date range.",
            )
        if parsed.business_query is not None or parsed.metric is not None:
            return ParserPolicyDecision(
                action=ParserPolicyAction.PROCEED,
                reasoning_notes="No explicit date range provided; defaulting to overall history.",
            )
        if not parsed.has_business_signal:
            return ParserPolicyDecision(
                action=ParserPolicyAction.REJECT,
                reasoning_notes="No supported SmartRest metric or business tool keyword found.",
            )
        return ParserPolicyDecision(
            action=ParserPolicyAction.CLARIFY,
            clarification_question=_clarification_question(parsed.language),
            reasoning_notes="Supported SmartRest planning requires an explicit date range.",
        )

    if parsed.business_query is not None:
        return ParserPolicyDecision(
            action=ParserPolicyAction.PROCEED,
            reasoning_notes="Business query parse is complete enough to proceed.",
        )

    if parsed.metric is not None:
        return ParserPolicyDecision(
            action=ParserPolicyAction.PROCEED,
            reasoning_notes="Metric parse is complete enough to proceed.",
        )

    return ParserPolicyDecision(
        action=ParserPolicyAction.REJECT,
        reasoning_notes=(
            "Parsed request did not resolve to a supported SmartRest metric "
            "or business query."
        ),
    )


def _clarification_question(language: str) -> str:
    if language == "hy":
        return "Խնդրում եմ նշեք ժամանակահատվածը YYYY-MM-DD to YYYY-MM-DD ձևաչափով:"
    if language == "ru":
        return "Пожалуйста, укажите диапазон дат в формате YYYY-MM-DD to YYYY-MM-DD."
    return "Please provide a date range in YYYY-MM-DD to YYYY-MM-DD format."
