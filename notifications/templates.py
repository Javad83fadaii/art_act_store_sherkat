from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from notifications.enums import NotificationProviderType
from notifications.utils import render_text_template


@dataclass(slots=True)
class RenderedNotificationTemplate:
    """Rendered notification content."""

    subject: str
    body: str


@dataclass(slots=True)
class NotificationTemplate:
    """In-memory template definition."""

    key: str
    subject_template: str = ''
    body_template: str = ''
    default_providers: tuple[NotificationProviderType, ...] = field(default_factory=tuple)

    def render(self, context: Mapping[str, Any] | None = None) -> RenderedNotificationTemplate:
        return RenderedNotificationTemplate(
            subject=render_text_template(self.subject_template, context),
            body=render_text_template(self.body_template, context),
        )


class NotificationTemplateRegistry:
    """Registry for code-defined notification templates."""

    def __init__(self, templates: Iterable[NotificationTemplate] | None = None) -> None:
        self._templates: dict[str, NotificationTemplate] = {}
        for template in templates or ():
            self.register(template)

    def register(self, template: NotificationTemplate) -> None:
        self._templates[template.key] = template

    def get(self, key: str) -> NotificationTemplate:
        if key not in self._templates:
            raise KeyError(f'Notification template "{key}" is not registered.')
        return self._templates[key]
