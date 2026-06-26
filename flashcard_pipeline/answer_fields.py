from __future__ import annotations

import re
from dataclasses import dataclass


DASHES = r"\-\u2010\u2011\u2012\u2013\u2014\u2015\uff0d"
LEADING_FIGURE_RE = re.compile(
    rf"^\s*(?:\uadf8\ub9bc|Fig\.?|Figure)\s*"
    rf"\d+\s*[{DASHES}]\s*\d+[A-Za-z]?\s*[.:．]?\s*",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+")
PANEL_ONLY_RE = re.compile(r"^\s*[A-Z](?:\s*[~\-–—]\s*[A-Z]|\s*,\s*[A-Z])*\s*[,.]?\s*$")
PANEL_PREFIX_RE = re.compile(r"^\s*[A-Z](?:\s*[~\-–—]\s*[A-Z])?\s*[,.:]\s*")
INLINE_PANEL_RE = re.compile(r"^(?P<title>[^,.。]{2,30}?)\s+(?P<label>[A-Z])\s*[,.:]\s*(?P<body>.+)$")
DISEASE_CONTEXT_RE = re.compile(r"^(?:.+?(?:에|에서)\s*발생(?:한|된)\s+)(?P<term>[^,.;。]+)$")
SENTENCE_LIKE_END_RE = re.compile(r"(?:다|된다|한다|있다|없다|보인다|관찰된다)$")


@dataclass(frozen=True)
class AnswerFields:
    answer_text: str
    answer_explanation: str


def compact_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_leading_figure_label(value: object) -> str:
    return LEADING_FIGURE_RE.sub("", str(value or ""), count=1).lstrip(" .:．").strip()


def split_first_sentence(value: str) -> tuple[str, str]:
    match = SENTENCE_SPLIT_RE.search(value)
    if not match:
        return value.strip().rstrip("."), ""
    first = value[: match.start()].strip().rstrip(".")
    rest = value[match.end() :].strip()
    return first, rest


def strip_panel_prefix(value: str) -> str:
    text = value.strip()
    while True:
        next_text = PANEL_PREFIX_RE.sub("", text, count=1).strip()
        if next_text == text:
            return text
        text = next_text


def normalize_answer_term(value: str) -> str:
    term = strip_panel_prefix(value)
    context_match = DISEASE_CONTEXT_RE.match(term)
    if context_match:
        candidate = context_match.group("term").strip()
        if 1 <= len(candidate) <= 24:
            term = candidate
    return compact_text(term).rstrip(".")


def is_title_like(value: str) -> bool:
    text = compact_text(value)
    if not text or len(text) > 25:
        return False
    return not SENTENCE_LIKE_END_RE.search(text)


def answer_fields_from_caption(value: object) -> AnswerFields:
    body = strip_leading_figure_label(value)
    return answer_fields_from_body(body)


def answer_fields_from_body(value: object) -> AnswerFields:
    body = compact_text(value)
    if not body:
        return AnswerFields("", "")

    first, rest = split_first_sentence(body)
    if PANEL_ONLY_RE.match(first) and rest:
        return answer_fields_from_body(rest)

    inline = INLINE_PANEL_RE.match(body)
    if inline:
        title = normalize_answer_term(inline.group("title"))
        if is_title_like(title):
            explanation = f"{inline.group('label')}, {inline.group('body').strip()}"
            return AnswerFields(title, compact_text(explanation))

    candidate = normalize_answer_term(first)
    if rest and is_title_like(candidate):
        return AnswerFields(candidate, rest)

    if not rest:
        return AnswerFields(normalize_answer_term(body), "")

    return AnswerFields(body, "")


def answer_is_caption_derived(answer_text: object, caption_text: object) -> bool:
    answer = compact_text(answer_text)
    if not answer:
        return True
    caption = compact_text(caption_text)
    stripped_caption = compact_text(strip_leading_figure_label(caption_text))
    fields = answer_fields_from_caption(caption_text)
    derived_values = {
        caption,
        stripped_caption,
        compact_text(fields.answer_text),
    }
    return answer in {value for value in derived_values if value}
