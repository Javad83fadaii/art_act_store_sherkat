from __future__ import annotations

import importlib.util
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from notifications.dispatcher import NotificationDispatchResult, NotificationDispatcher
from notifications.enums import NotificationProviderType
from notifications.models import NotificationDelivery, StoredNotificationTemplate
from notifications.providers import (
    BaseNotificationProvider,
    EmailProvider,
    NotificationPayload,
    SMSProvider,
    TelegramProvider,
)
from notifications.templates import NotificationTemplate, NotificationTemplateRegistry
from notifications.utils import merge_metadata, normalize_recipients, render_text_template


logger = logging.getLogger(__name__)


class NotificationService:
    """Application entry point for dispatching notifications."""

    def __init__(
        self,
        *,
        template_registry: NotificationTemplateRegistry | None = None,
    ) -> None:
        self.template_registry = template_registry or NotificationTemplateRegistry()

    def register_template(self, template: NotificationTemplate) -> None:
        """Register an in-memory notification template."""
        self.template_registry.register(template)

    def send(
        self,
        *,
        event: str,
        recipients: Iterable[str] | str | None,
        subject: str = '',
        body: str = '',
        providers: Sequence[NotificationProviderType | str] | None = None,
        context: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> NotificationDispatchResult:
        """Dispatch a notification through one or more providers."""
        payload = NotificationPayload(
            event=event,
            recipients=normalize_recipients(recipients),
            subject=subject,
            body=body,
            context=dict(context or {}),
            metadata=merge_metadata(metadata),
        )
        dispatcher = NotificationDispatcher(self._build_providers(providers))
        result = dispatcher.dispatch(payload)
        self._store_delivery_logs(result)
        return result

    def send_template(
        self,
        *,
        event: str = '',
        template_key: str = '',
        recipients: Iterable[str] | str | None = None,
        context: Mapping[str, Any] | None = None,
        providers: Sequence[NotificationProviderType | str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        template: str = '',
        channels: Sequence[NotificationProviderType | str] | None = None,
        user: Any | None = None,
    ) -> NotificationDispatchResult:
        """Render a template and dispatch it through the selected providers."""
        resolved_template_key = str(template_key or template or '').strip()
        if not resolved_template_key:
            raise ValueError('template_key or template is required.')

        selected_providers = self._normalize_provider_types(providers or channels)
        try:
            template_subject, template_body, template_providers = self._resolve_template(
                template_key=resolved_template_key,
                context=context,
            )
        except KeyError:
            fallback_providers = selected_providers or (NotificationProviderType.SMS,)
            if not self._can_dispatch_sms_pattern_only(
                template_key=resolved_template_key,
                providers=fallback_providers,
            ):
                raise
            template_subject, template_body, template_providers = '', '', fallback_providers

        selected_providers = selected_providers or template_providers
        resolved_recipients = recipients
        if resolved_recipients is None:
            resolved_recipients = self._resolve_user_recipients(
                user=user,
                providers=selected_providers,
            )

        resolved_metadata = merge_metadata(
            metadata,
            {
                'template_key': resolved_template_key,
            },
        )
        if NotificationProviderType.SMS in selected_providers:
            resolved_metadata['sms_pattern'] = resolved_template_key

        return self.send(
            event=str(event or resolved_template_key).strip(),
            recipients=resolved_recipients,
            subject=template_subject,
            body=template_body,
            providers=selected_providers,
            context=context,
            metadata=resolved_metadata,
        )

    def _resolve_template(
        self,
        *,
        template_key: str,
        context: Mapping[str, Any] | None,
    ) -> tuple[str, str, tuple[NotificationProviderType, ...]]:
        stored_template = (
            StoredNotificationTemplate.objects.filter(key=template_key, is_active=True)
            .order_by('channel')
            .first()
        )
        if stored_template is not None:
            return (
                render_text_template(stored_template.subject_template, context),
                render_text_template(stored_template.body_template, context),
                (NotificationProviderType(stored_template.channel),),
            )

        template = self.template_registry.get(template_key)
        rendered = template.render(context)
        return rendered.subject, rendered.body, template.default_providers

    def _build_providers(
        self,
        providers: Sequence[NotificationProviderType | str] | None,
    ) -> list[BaseNotificationProvider]:
        provider_order = self._normalize_provider_types(providers) or tuple(NotificationProviderType)
        instances: list[BaseNotificationProvider] = []
        for provider in provider_order:
            instances.append(self._make_provider(provider))
        return instances

    def _normalize_provider_types(
        self,
        providers: Sequence[NotificationProviderType | str] | None,
    ) -> tuple[NotificationProviderType, ...] | None:
        if providers is None:
            return None
        normalized: list[NotificationProviderType] = []
        for provider in providers:
            provider_type = provider if isinstance(provider, NotificationProviderType) else NotificationProviderType(provider)
            if provider_type not in normalized:
                normalized.append(provider_type)
        return tuple(normalized)

    def _make_provider(self, provider_type: NotificationProviderType) -> BaseNotificationProvider:
        providers_map: dict[NotificationProviderType, type[BaseNotificationProvider]] = {
            NotificationProviderType.EMAIL: EmailProvider,
            NotificationProviderType.SMS: SMSProvider,
            NotificationProviderType.TELEGRAM: TelegramProvider,
        }
        return providers_map[provider_type]()

    def _can_dispatch_sms_pattern_only(
        self,
        *,
        template_key: str,
        providers: Sequence[NotificationProviderType],
    ) -> bool:
        return (
            bool(providers)
            and all(provider == NotificationProviderType.SMS for provider in providers)
        )

    def _resolve_user_recipients(
        self,
        *,
        user: Any | None,
        providers: Sequence[NotificationProviderType],
    ) -> Iterable[str] | str | None:
        if user is None:
            return None
        if len(providers) != 1:
            raise ValueError('Automatic recipient resolution from user requires exactly one provider/channel.')

        provider = providers[0]
        if provider == NotificationProviderType.SMS:
            recipient = getattr(user, 'phone_number', None)
        elif provider == NotificationProviderType.EMAIL:
            recipient = getattr(user, 'email', None)
        elif provider == NotificationProviderType.TELEGRAM:
            recipient = getattr(user, 'telegram_id', None)
        else:
            recipient = None

        return [recipient] if recipient else []

    def _store_delivery_logs(self, result: NotificationDispatchResult) -> None:
        deliveries = [
            NotificationDelivery(
                event=result.payload.event,
                channel=provider_result.channel.value,
                provider=provider_result.provider.value,
                recipients=list(provider_result.recipients),
                subject=result.payload.subject,
                body=result.payload.body,
                status=provider_result.status.value,
                detail=provider_result.detail,
                metadata=merge_metadata(result.payload.metadata, provider_result.metadata),
            )
            for provider_result in result.results
        ]
        if deliveries:
            NotificationDelivery.objects.bulk_create(deliveries)


notification_service = NotificationService()


def _can_use_celery_tasks() -> bool:
    """Report whether Celery task execution is available in this runtime."""
    if importlib.util.find_spec('celery') is None:
        return False

    try:
        from notifications.tasks import dispatch_notification_task
    except Exception:
        return False

    return hasattr(dispatch_notification_task, 'apply')


def _run_notification_task(
    *,
    event: str,
    recipients: Iterable[str] | str | None,
    subject: str = '',
    body: str = '',
    providers: Sequence[NotificationProviderType | str] | None = None,
    context: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Execute notification dispatch through the Celery task interface."""
    from notifications.tasks import dispatch_notification_task

    serialized_providers = None
    if providers is not None:
        serialized_providers = [
            provider.value if isinstance(provider, NotificationProviderType) else str(provider)
            for provider in providers
        ]

    dispatch_notification_task.apply(
        kwargs={
            'event': event,
            'recipients': recipients,
            'subject': subject,
            'body': body,
            'providers': serialized_providers,
            'context': dict(context or {}),
            'metadata': dict(metadata or {}),
        },
        throw=True,
    )


def _run_template_notification_task(
    *,
    event: str,
    template_key: str,
    recipients: Iterable[str] | str | None,
    context: Mapping[str, Any] | None = None,
    providers: Sequence[NotificationProviderType | str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Execute template notification dispatch through the Celery task interface."""
    from notifications.tasks import dispatch_template_notification_task

    serialized_providers = None
    if providers is not None:
        serialized_providers = [
            provider.value if isinstance(provider, NotificationProviderType) else str(provider)
            for provider in providers
        ]

    dispatch_template_notification_task.apply(
        kwargs={
            'event': event,
            'template_key': template_key,
            'recipients': recipients,
            'context': dict(context or {}),
            'providers': serialized_providers,
            'metadata': dict(metadata or {}),
        },
        throw=True,
    )


def send_notification_safely(
    *,
    event: str,
    recipients: Iterable[str] | str | None,
    subject: str = '',
    body: str = '',
    providers: Sequence[NotificationProviderType | str] | None = None,
    context: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> NotificationDispatchResult | None:
    """Dispatch a notification without interrupting the caller flow."""
    try:
        if _can_use_celery_tasks():
            _run_notification_task(
                event=event,
                recipients=recipients,
                subject=subject,
                body=body,
                providers=providers,
                context=context,
                metadata=metadata,
            )
            return None
        return notification_service.send(
            event=event,
            recipients=recipients,
            subject=subject,
            body=body,
            providers=providers,
            context=context,
            metadata=metadata,
        )
    except Exception:
        logger.exception('Notification dispatch failed for event %s', event)
        return None


def send_template_notification_safely(
    *,
    event: str,
    template_key: str,
    recipients: Iterable[str] | str | None,
    context: Mapping[str, Any] | None = None,
    providers: Sequence[NotificationProviderType | str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> NotificationDispatchResult | None:
    """Render and dispatch a template without interrupting the caller flow."""
    try:
        if _can_use_celery_tasks():
            _run_template_notification_task(
                event=event,
                template_key=template_key,
                recipients=recipients,
                context=context,
                providers=providers,
                metadata=metadata,
            )
            return None
        return notification_service.send_template(
            event=event,
            template_key=template_key,
            recipients=recipients,
            context=context,
            providers=providers,
            metadata=metadata,
        )
    except Exception:
        logger.exception('Template notification dispatch failed for event %s', event)
        return None
