from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings


@dataclass(frozen=True, slots=True)
class SMSPatternDefinition:
    """Normalized SMS pattern settings entry."""

    name: str
    code: str
    variables: tuple[str, ...]


class SMSPatternRegistry:
    """Resolve SMS patterns from Django settings."""

    setting_name = 'SMS_PATTERNS'

    def __init__(self, patterns: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._patterns = self._normalize_patterns(
            patterns if patterns is not None else getattr(settings, self.setting_name, {})
        )

    def get(self, name: str) -> SMSPatternDefinition:
        try:
            return self._patterns[name]
        except KeyError as exc:
            raise KeyError(f'SMS pattern "{name}" is not configured.') from exc

    def has(self, name: str) -> bool:
        return name in self._patterns

    def as_dict(self) -> dict[str, SMSPatternDefinition]:
        return dict(self._patterns)

    def _normalize_patterns(
        self,
        patterns: Mapping[str, Mapping[str, Any]] | None,
    ) -> dict[str, SMSPatternDefinition]:
        normalized: dict[str, SMSPatternDefinition] = {}
        for pattern_name, raw_pattern in dict(patterns or {}).items():
            if not isinstance(raw_pattern, Mapping):
                continue

            code = str(raw_pattern.get('code') or '').strip()
            variables = tuple(
                str(variable).strip()
                for variable in raw_pattern.get('variables', ())
                if str(variable).strip()
            )
            normalized[pattern_name] = SMSPatternDefinition(
                name=str(pattern_name).strip(),
                code=code,
                variables=variables,
            )
        return normalized
