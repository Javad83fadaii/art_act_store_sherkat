from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from django.db import models

from notifications.enums import NotificationStatus
from notifications.providers import BaseNotificationProvider, NotificationPayload, NotificationSendResult


@dataclass(slots=True)
class NotificationDispatchResult:
    """Aggregated dispatch output for all invoked providers."""

    payload: NotificationPayload
    results: list[NotificationSendResult] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        return bool(self.results) and all(
            result.status in {NotificationStatus.SENT, NotificationStatus.SKIPPED}
            for result in self.results
        )


class NotificationDispatcher:
    """Dispatch notifications across multiple providers based on user settings."""

    def __init__(self, providers: list[BaseNotificationProvider]) -> None:
        self.providers = providers

    def dispatch(self, payload: NotificationPayload) -> NotificationDispatchResult:
        if not self.providers:
            return NotificationDispatchResult(payload=payload, results=[])

        effective_providers = self._resolve_user_providers(payload)
        if not effective_providers:
            return NotificationDispatchResult(payload=payload, results=[])

        indexed_results: dict[int, NotificationSendResult] = {}
        with ThreadPoolExecutor(max_workers=len(effective_providers)) as executor:
            future_map = {
                executor.submit(provider.send, payload): (index, provider)
                for index, provider in enumerate(effective_providers)
            }
            for future in as_completed(future_map):
                index, provider = future_map[future]
                try:
                    indexed_results[index] = future.result()
                except Exception as exc:
                    indexed_results[index] = provider.build_result(
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        detail=f'Provider execution failed: {exc}',
                    )

        ordered_results = [indexed_results[index] for index in sorted(indexed_results)]
        return NotificationDispatchResult(payload=payload, results=ordered_results)

    def _resolve_user_providers(self, payload: NotificationPayload) -> list[BaseNotificationProvider]:
        """Filter providers based on target user's notification channel preferences."""
        user = self._extract_user(payload)
        if user is None:
            return self.providers

        user_settings = getattr(user, 'preferred_contact_methods', None)
        if user_settings is None or not isinstance(user_settings, (list, tuple, set)) or len(user_settings) == 0:
            # Rule 5: If no settings specified for user, preserve default project behavior.
            return self.providers

        user_channels = {str(item).strip().lower() for item in user_settings if str(item).strip()}
        filtered = [
            provider for provider in self.providers
            if provider.channel.value.lower() in user_channels or provider.provider_type.value.lower() in user_channels
        ]
        return filtered

    def _extract_user(self, payload: NotificationPayload) -> Any | None:
        """Extract user object from payload context, metadata, or recipients."""
        user = payload.context.get('user') or payload.metadata.get('user')
        if user is not None and hasattr(user, 'preferred_contact_methods'):
            return user

        user_id = payload.context.get('user_id') or payload.metadata.get('user_id')
        if user_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                found = User.objects.filter(pk=user_id).first()
                if found:
                    return found
            except Exception:
                pass

        if payload.recipients:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                found = User.objects.filter(
                    models.Q(email__in=payload.recipients) |
                    models.Q(phone_number__in=payload.recipients) |
                    models.Q(telegram_id__in=payload.recipients)
                ).first()
                if found:
                    return found
            except Exception:
                pass

        return None
