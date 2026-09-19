from __future__ import annotations

from enum import Enum


class ChoiceEnum(str, Enum):
    """Base enum with helpers for Django choices."""

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(member.value, member.label) for member in cls]

    @property
    def label(self) -> str:
        return self.name.replace('_', ' ').title()


class NotificationChannel(ChoiceEnum):
    EMAIL = 'email'
    SMS = 'sms'
    TELEGRAM = 'telegram'


class NotificationProviderType(ChoiceEnum):
    EMAIL = 'email'
    SMS = 'sms'
    TELEGRAM = 'telegram'


class NotificationStatus(ChoiceEnum):
    PENDING = 'pending'
    SENT = 'sent'
    FAILED = 'failed'
    SKIPPED = 'skipped'
