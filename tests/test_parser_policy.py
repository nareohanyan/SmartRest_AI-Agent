from __future__ import annotations

from app.agent.parser_policy import decide_policy
from app.agent.parser_structures import ParserPolicyAction
from app.agent.planning import _parse_question


def test_policy_rejects_non_business_prompt_without_date() -> None:
    parsed = _parse_question("How is the weather?")

    decision = decide_policy(parsed)

    assert decision.action is ParserPolicyAction.REJECT


def test_policy_defaults_business_prompt_without_date_to_overall() -> None:
    parsed = _parse_question("Եկամուտս ինչքա՞նա կազմել։")

    decision = decide_policy(parsed)

    assert decision.action is ParserPolicyAction.PROCEED
    assert decision.clarification_question is None


def test_policy_proceeds_for_supported_business_query() -> None:
    parsed = _parse_question("Նախորդ երկու ամսվա մեջ ամենաշատ վաճառված ապրանքը ո՞րն է եղել։")

    decision = decide_policy(parsed)

    assert decision.action is ParserPolicyAction.PROCEED
