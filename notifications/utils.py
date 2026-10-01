from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class SafeFormatDict(dict[str, Any]):
    """Keep unknown placeholders intact during string formatting."""

    def __missing__(self, key: str) -> str:
        return '{' + key + '}'


def normalize_recipients(recipients: Iterable[str] | str | None) -> list[str]:
    """Normalize recipients to a de-duplicated ordered list of strings."""
    if recipients is None:
        return []

    if isinstance(recipients, str):
        items = [recipients]
    else:
        items = [str(item).strip() for item in recipients]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def render_text_template(template: str, context: Mapping[str, Any] | None = None) -> str:
    """Render a text template with a tolerant formatter."""
    return (template or '').format_map(SafeFormatDict(context or {}))


def merge_metadata(*sources: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge metadata dictionaries from left to right."""
    merged: dict[str, Any] = {}
    for source in sources:
        if source:
            merged.update(source)
    return merged
