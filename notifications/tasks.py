from __future__ import annotations

try:
    from celery import shared_task
except ImportError:
    def shared_task(func):
        func.delay = func
        return func

from notifications.services import NotificationService


@shared_task
def dispatch_notification_task(
    event: str,
    recipients: list[str] | str | None,
    subject: str = '',
    body: str = '',
    providers: list[str] | None = None,
    context: dict | None = None,
    metadata: dict | None = None,
) -> dict[str, object]:
    """Task wrapper around the notification service."""
    service = NotificationService()
    result = service.send(
        event=event,
        recipients=recipients,
        subject=subject,
        body=body,
        providers=providers,
        context=context,
        metadata=metadata,
    )
    return {
        'event': result.payload.event,
        'providers': [item.provider.value for item in result.results],
        'statuses': [item.status.value for item in result.results],
    }


@shared_task
def dispatch_template_notification_task(
    event: str,
    template_key: str,
    recipients: list[str] | str | None,
    context: dict | None = None,
    providers: list[str] | None = None,
    metadata: dict | None = None,
) -> dict[str, object]:
    """Task wrapper around template-based notification dispatch."""
    service = NotificationService()
    result = service.send_template(
        event=event,
        template_key=template_key,
        recipients=recipients,
        context=context,
        providers=providers,
        metadata=metadata,
    )
    return {
        'event': result.payload.event,
        'providers': [item.provider.value for item in result.results],
        'statuses': [item.status.value for item in result.results],
    }
