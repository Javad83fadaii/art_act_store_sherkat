from __future__ import annotations

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus

from .base import BaseNotificationProvider, NotificationPayload, NotificationSendResult


class SMSProvider(BaseNotificationProvider):
    """Skeleton SMS provider."""

    provider_type = NotificationProviderType.SMS
    channel = NotificationChannel.SMS

    def send(self, payload: NotificationPayload) -> NotificationSendResult:
        return self.build_result(
            payload=payload,
            status=NotificationStatus.SKIPPED,
            detail='SMS provider is configured as a skeleton and does not send messages yet.',
        )
