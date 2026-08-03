import ast
import json
import re
from typing import Any, Iterable, Optional


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, str):
            return first
        return str(first)
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _strip_code_fence(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    # Gracefully handle partial or malformed fenced blocks.
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_first_bracket_block(text: str) -> Optional[str]:
    openers = {"{": "}", "[": "]"}
    closers = {"}": "{", "]": "["}
    start_idx = -1
    for idx, ch in enumerate(text):
        if ch in openers:
            start_idx = idx
            break

    if start_idx < 0:
        return None

    stack = []
    in_string = False
    escape = False
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in openers:
            stack.append(ch)
            continue

        if ch in closers:
            if not stack or stack[-1] != closers[ch]:
                return None
            stack.pop()
            if not stack:
                return text[start_idx : idx + 1].strip()
    return None


def normalize_llm_output(output: Any, strip_labels: Iterable[str] = ()) -> str:
    text = _coerce_text(output).strip()

    for label in strip_labels:
        text = re.sub(
            rf"^\s*{re.escape(label)}\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

    text = _strip_code_fence(text)
    text = re.sub(r"^\s*json\s*(?:\r?\n)+", "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_structured_output(output: Any, strip_labels: Iterable[str] = ()) -> Any:
    cleaned = normalize_llm_output(output, strip_labels=strip_labels)

    parse_errors = []
    for parser in (ast.literal_eval, json.loads):
        try:
            return parser(cleaned)
        except Exception as exc:
            parse_errors.append(exc)

    fragment = _extract_first_bracket_block(cleaned)
    if fragment and fragment != cleaned:
        for parser in (ast.literal_eval, json.loads):
            try:
                return parser(fragment)
            except Exception as exc:
                parse_errors.append(exc)

    if parse_errors:
        raise ValueError(cleaned) from parse_errors[-1]
    raise ValueError(cleaned)
