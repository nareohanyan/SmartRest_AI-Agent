from __future__ import annotations

import re
from functools import cache

_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_SMALLTALK_TRAILING_PUNCT_RE = re.compile(r"[!?.…]+$")
_SMALLTALK_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’]+")
_TEXT_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’-]+")
_ARMENIAN_TOKEN_SUFFIXES = ("ս", "դ", "ը", "ն")
_TERM_CORRECTIONS = {
    "վաճարված": "վաճառված",
}


def normalize_text(question: str) -> str:
    normalized = question.lower().strip().replace("’", "'")
    normalized = _TEXT_TOKEN_NORMALIZE_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for source, target in _TERM_CORRECTIONS.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return normalized


def normalize_smalltalk_text(question: str) -> str:
    normalized = question.lower().strip()
    normalized = normalized.replace("’", "'")
    normalized = _SMALLTALK_TRAILING_PUNCT_RE.sub("", normalized)
    normalized = _SMALLTALK_TOKEN_NORMALIZE_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


@cache
def _cached_base_tokens(base_terms: tuple[str, ...]) -> frozenset[str]:
    return frozenset(base_terms)


def build_semantic_base_tokens(*term_groups: set[str]) -> frozenset[str]:
    base_terms: set[str] = set()
    for group in term_groups:
        base_terms.update(term for term in group if " " not in term)
    return _cached_base_tokens(tuple(sorted(base_terms)))


def semantic_token_candidates(token: str, *, base_tokens: frozenset[str]) -> set[str]:
    candidates = {token}
    if _ARMENIAN_CHAR_RE.search(token) is None:
        return candidates

    for suffix in _ARMENIAN_TOKEN_SUFFIXES:
        if not token.endswith(suffix):
            continue
        if len(token) <= len(suffix) + 1:
            continue
        stripped = token[: -len(suffix)]
        if stripped in base_tokens:
            candidates.add(stripped)
    return candidates


def semantic_tokens(
    normalized_question: str,
    *,
    base_tokens: frozenset[str],
) -> set[str]:
    tokens: set[str] = set()
    for token in normalized_question.split():
        tokens.update(semantic_token_candidates(token, base_tokens=base_tokens))
    return tokens


def count_term_hits(normalized_question: str, tokens: set[str], terms: set[str]) -> int:
    hits = 0
    for term in terms:
        if " " in term:
            if term in normalized_question:
                hits += 1
            continue
        if term in tokens or any(token.startswith(term) for token in tokens):
            hits += 1
    return hits
