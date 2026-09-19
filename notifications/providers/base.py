from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from notifications.enums import (
    NotificationChannel,
    NotificationProviderType,
    NotificationStatus,
)


@dataclass(slots=True)
class NotificationPayload:
    """Normalized notification data passed to providers."""

    event: str
    recipients: list[str]
    subject: str = ''
    body: str = ''
    context: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NotificationSendResult:
    """Provider execution result."""

    provider: NotificationProviderType
    channel: NotificationChannel
    status: NotificationStatus
    recipients: Sequence[str]
    detail: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseNotificationProvider(ABC):
    """Abstract provider contract for all notification channels."""

    provider_type: NotificationProviderType
    channel: NotificationChannel

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    @property
    def name(self) -> str:
        return self.provider_type.value

    def build_result(
        self,
        *,
        payload: NotificationPayload,
        status: NotificationStatus,
        detail: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> NotificationSendResult:
        """Build a standard provider result object."""
        return NotificationSendResult(
            provider=self.provider_type,
            channel=self.channel,
            status=status,
            recipients=list(payload.recipients),
            detail=detail,
            metadata=dict(metadata or {}),
        )

    def is_available(self, payload: NotificationPayload) -> bool:
        """Report whether the provider is allowed to handle the payload."""
        return self.enabled and bool(payload.recipients)

    @abstractmethod
    def send(self, payload: NotificationPayload) -> NotificationSendResult:
        """Handle notification delivery for a single provider."""
