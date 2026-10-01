from __future__ import annotations

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus

from .base import BaseNotificationProvider, NotificationPayload, NotificationSendResult


class TelegramProvider(BaseNotificationProvider):
    """Skeleton Telegram provider."""

    provider_type = NotificationProviderType.TELEGRAM
    channel = NotificationChannel.TELEGRAM

    def send(self, payload: NotificationPayload) -> NotificationSendResult:
        return self.build_result(
            payload=payload,
            status=NotificationStatus.SKIPPED,
            detail='Telegram provider is configured as a skeleton and does not send messages yet.',
        )
