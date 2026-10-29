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
from notifications.sms_patterns import SMSPatternRegistry
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
        effective_providers = selected_providers or self._resolve_template_providers(resolved_template_key)
        base_context = dict(context or {})
        if user is not None and 'user' not in base_context:
            base_context['user'] = user

        aggregate_results = []
        aggregate_recipients: list[str] = []
        aggregate_subject = ''
        aggregate_body = ''
        aggregate_metadata = merge_metadata(
            metadata,
            {
                'template_key': resolved_template_key,
            },
        )
        resolved_event = str(event or resolved_template_key).strip()

        for provider in effective_providers:
            provider_subject, provider_body, provider_context, provider_metadata = self._resolve_template_for_provider(
                template_key=resolved_template_key,
                provider=provider,
                context=base_context,
                metadata=aggregate_metadata,
            )
            provider_recipients = recipients
            if provider_recipients is None:
                provider_recipients = self._resolve_user_recipients(
                    user=user,
                    providers=(provider,),
                )

            provider_result = self.send(
                event=resolved_event,
                recipients=provider_recipients,
                subject=provider_subject,
                body=provider_body,
                providers=(provider,),
                context=provider_context,
                metadata=provider_metadata,
            )
            aggregate_results.extend(provider_result.results)
            aggregate_recipients.extend(provider_result.payload.recipients)
            if not aggregate_subject and provider_subject:
                aggregate_subject = provider_subject
            if not aggregate_body and provider_body:
                aggregate_body = provider_body

        return NotificationDispatchResult(
            payload=NotificationPayload(
                event=resolved_event,
                recipients=normalize_recipients(aggregate_recipients),
                subject=aggregate_subject,
                body=aggregate_body,
                context=base_context,
                metadata=aggregate_metadata,
            ),
            results=aggregate_results,
        )

    def _resolve_template_providers(
        self,
        template_key: str,
    ) -> tuple[NotificationProviderType, ...]:
        stored_channels = [
            NotificationProviderType(channel)
            for channel in StoredNotificationTemplate.objects.filter(key=template_key, is_active=True)
            .order_by('channel')
            .values_list('channel', flat=True)
        ]
        resolved: list[NotificationProviderType] = []

        try:
            for provider in self.template_registry.get(template_key).available_providers:
                if provider not in resolved:
                    resolved.append(provider)
        except KeyError:
            pass

        for provider in stored_channels:
            if provider not in resolved:
                resolved.append(provider)

        if SMSPatternRegistry().has(template_key) and NotificationProviderType.SMS not in resolved:
            resolved.append(NotificationProviderType.SMS)

        if not resolved:
            raise KeyError(f'Notification template "{template_key}" is not registered.')
        return tuple(resolved)

    def _resolve_template_for_provider(
        self,
        *,
        template_key: str,
        provider: NotificationProviderType,
        context: Mapping[str, Any] | None,
        metadata: Mapping[str, Any] | None,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        resolved_context = dict(context or {})
        resolved_metadata = merge_metadata(
            metadata,
            {
                'template_key': template_key,
            },
        )

        stored_template = (
            StoredNotificationTemplate.objects.filter(
                key=template_key,
                channel=provider.value,
                is_active=True,
            )
            .order_by('channel')
            .first()
        )
        if stored_template is not None:
            return (
                render_text_template(stored_template.subject_template, resolved_context),
                render_text_template(stored_template.body_template, resolved_context),
                resolved_context,
                resolved_metadata,
            )

        try:
            template = self.template_registry.get(template_key)
            rendered = template.get_channel_template(provider).render(resolved_context)
            resolved_metadata = merge_metadata(resolved_metadata, rendered.metadata)
            return rendered.subject, rendered.body, rendered.context, resolved_metadata
        except KeyError:
            if provider == NotificationProviderType.SMS:
                resolved_metadata['sms_pattern'] = template_key
                return '', '', resolved_context, resolved_metadata
            raise

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
