from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.schemas.reports import ReportFilterKey, ReportType
from app.schemas.tools import (
    ResolveFilterValueResponse,
    ResolveFilterValueStatus,
)

_SUPPORTED_FILTERS_BY_REPORT: dict[ReportType, frozenset[ReportFilterKey]] = {
    report_id: frozenset(
        {
            ReportFilterKey.SOURCE,
            ReportFilterKey.COURIER,
            ReportFilterKey.LOCATION,
            ReportFilterKey.PHONE_NUMBER,
        }
    )
    for report_id in ReportType
}

_ARMENIAN_TO_LATIN = {
    "ա": "a",
    "բ": "b",
    "գ": "g",
    "դ": "d",
    "ե": "e",
    "զ": "z",
    "է": "e",
    "ը": "y",
    "թ": "t",
    "ժ": "zh",
    "ի": "i",
    "լ": "l",
    "խ": "kh",
    "ծ": "ts",
    "կ": "k",
    "հ": "h",
    "ձ": "dz",
    "ղ": "gh",
    "ճ": "ch",
    "մ": "m",
    "յ": "y",
    "ն": "n",
    "շ": "sh",
    "ո": "o",
    "չ": "ch",
    "պ": "p",
    "ջ": "j",
    "ռ": "r",
    "ս": "s",
    "վ": "v",
    "տ": "t",
    "ր": "r",
    "ց": "ts",
    "ւ": "v",
    "փ": "p",
    "ք": "q",
    "և": "ev",
    "օ": "o",
    "ֆ": "f",
}

_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

_MAX_CANDIDATES = 5
_AUTO_RESOLVE_TEXT_SCORE_THRESHOLD = 7.0
_AUTO_RESOLVE_TEXT_SCORE_MARGIN = 2.0


def supported_filter_keys(report_id: ReportType) -> frozenset[ReportFilterKey]:
    return _SUPPORTED_FILTERS_BY_REPORT.get(report_id, frozenset())


def normalize_phone_value(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 6 or len(digits) > 15:
        return None
    if digits.startswith("374") and len(digits) in {11, 12}:
        return f"0{digits[3:]}"
    return digits


def _latinize_text(value: str) -> str:
    lowered = value.lower()
    buffer: list[str] = []
    index = 0
    while index < len(lowered):
        if lowered[index : index + 2] == "ու":
            buffer.append("u")
            index += 2
            continue

        char = lowered[index]
        if char in _ARMENIAN_TO_LATIN:
            buffer.append(_ARMENIAN_TO_LATIN[char])
        elif char in _CYRILLIC_TO_LATIN:
            buffer.append(_CYRILLIC_TO_LATIN[char])
        else:
            buffer.append(char)
        index += 1
    return "".join(buffer)


def normalize_lookup_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = (
        value.replace("֊", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("_", " ")
        .strip()
        .lower()
    )
    normalized = " ".join(normalized.split())
    if not normalized:
        return None
    latinized = _latinize_text(normalized)
    latinized = re.sub(r"[^a-z0-9]+", " ", latinized)
    latinized = " ".join(latinized.split())
    return latinized or None


def _digit_tokens(value: str) -> set[str]:
    return set(re.findall(r"\d+", value))


def _word_tokens(value: str) -> set[str]:
    return {token for token in value.split() if not token.isdigit() and len(token) >= 3}


def _tokens_match(left: str, right: str) -> bool:
    return (
        left == right
        or left in right
        or right in left
        or SequenceMatcher(None, left, right).ratio() >= 0.72
    )


def _has_word_overlap(left_tokens: set[str], right_tokens: set[str]) -> bool:
    return any(_tokens_match(left, right) for left in left_tokens for right in right_tokens)


def _text_candidate_score(
    *,
    filter_key: ReportFilterKey,
    raw_value: str,
    candidate: str,
) -> float:
    raw_lookup = normalize_lookup_text(raw_value)
    candidate_lookup = normalize_lookup_text(candidate)
    if raw_lookup is None or candidate_lookup is None:
        return 0.0

    raw_tokens = set(raw_lookup.split())
    candidate_tokens = set(candidate_lookup.split())
    raw_digit_tokens = _digit_tokens(raw_lookup)
    candidate_digit_tokens = _digit_tokens(candidate_lookup)
    raw_word_tokens = _word_tokens(raw_lookup)
    candidate_word_tokens = _word_tokens(candidate_lookup)

    if filter_key is ReportFilterKey.LOCATION and raw_digit_tokens:
        if not raw_digit_tokens & candidate_digit_tokens:
            return 0.0
    if filter_key is ReportFilterKey.LOCATION and raw_word_tokens:
        if not _has_word_overlap(raw_word_tokens, candidate_word_tokens):
            return 0.0
    if filter_key in {ReportFilterKey.COURIER, ReportFilterKey.SOURCE} and raw_word_tokens:
        if (
            not _has_word_overlap(raw_word_tokens, candidate_word_tokens)
            and raw_lookup not in candidate_lookup
            and candidate_lookup not in raw_lookup
        ):
            return 0.0

    shared_tokens = raw_tokens & candidate_tokens
    score = float(len(shared_tokens) * 3)
    if shared_tokens and shared_tokens == raw_tokens:
        score += 2.0
    if raw_lookup in candidate_lookup or candidate_lookup in raw_lookup:
        score += 3.0
    if raw_digit_tokens:
        score += float(len(raw_digit_tokens & candidate_digit_tokens) * 4)
    score += SequenceMatcher(None, raw_lookup, candidate_lookup).ratio() * 5.0
    return score


def resolve_filter_value_from_catalog(
    *,
    report_id: ReportType,
    filter_key: ReportFilterKey,
    raw_value: str,
    catalog_values: list[str],
) -> ResolveFilterValueResponse:
    if filter_key not in supported_filter_keys(report_id):
        return ResolveFilterValueResponse(
            status=ResolveFilterValueStatus.UNSUPPORTED,
            matched_value=None,
            candidates=[],
        )

    if filter_key is ReportFilterKey.PHONE_NUMBER:
        normalized_phone = normalize_phone_value(raw_value)
        if normalized_phone is None:
            return ResolveFilterValueResponse(
                status=ResolveFilterValueStatus.UNRESOLVED,
                matched_value=None,
                candidates=[],
            )
        for candidate in catalog_values:
            if normalize_phone_value(candidate) == normalized_phone:
                return ResolveFilterValueResponse(
                    status=ResolveFilterValueStatus.RESOLVED,
                    matched_value=candidate,
                    candidates=[],
                )
        return ResolveFilterValueResponse(
            status=ResolveFilterValueStatus.UNRESOLVED,
            matched_value=None,
            candidates=[],
        )

    normalized_raw = normalize_lookup_text(raw_value)
    if normalized_raw is None:
        return ResolveFilterValueResponse(
            status=ResolveFilterValueStatus.UNRESOLVED,
            matched_value=None,
            candidates=[],
        )

    for candidate in catalog_values:
        if normalize_lookup_text(candidate) == normalized_raw:
            return ResolveFilterValueResponse(
                status=ResolveFilterValueStatus.RESOLVED,
                matched_value=candidate,
                candidates=[],
            )

    ranked_candidates = sorted(
        (
            (
                _text_candidate_score(
                    filter_key=filter_key,
                    raw_value=raw_value,
                    candidate=candidate,
                ),
                candidate,
            )
            for candidate in catalog_values
        ),
        key=lambda item: (-item[0], item[1].lower()),
    )

    if filter_key in {ReportFilterKey.COURIER, ReportFilterKey.SOURCE} and ranked_candidates:
        top_score, top_candidate = ranked_candidates[0]
        next_score = ranked_candidates[1][0] if len(ranked_candidates) > 1 else 0.0
        if top_score >= _AUTO_RESOLVE_TEXT_SCORE_THRESHOLD and (
            next_score < 4.0 or (top_score - next_score) >= _AUTO_RESOLVE_TEXT_SCORE_MARGIN
        ):
            return ResolveFilterValueResponse(
                status=ResolveFilterValueStatus.RESOLVED,
                matched_value=top_candidate,
                candidates=[],
            )

    candidates = [
        candidate
        for score, candidate in ranked_candidates
        if score >= 4.0
    ][: _MAX_CANDIDATES]

    return ResolveFilterValueResponse(
        status=ResolveFilterValueStatus.UNRESOLVED,
        matched_value=None,
        candidates=candidates,
    )
