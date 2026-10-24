from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.utils import timezone

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus

from .base import BaseNotificationProvider, NotificationPayload, NotificationSendResult


logger = logging.getLogger(__name__)


class EmailProvider(BaseNotificationProvider):
    """Send email notifications through Django's configured email backend."""

    provider_type = NotificationProviderType.EMAIL
    channel = NotificationChannel.EMAIL

    def send(self, payload: NotificationPayload) -> NotificationSendResult:
        """Validate recipients and dispatch the email through Django settings."""
        validated_recipients, invalid_recipients = self._validate_recipients(payload.recipients)
        normalized_payload = NotificationPayload(
            event=payload.event,
            recipients=validated_recipients,
            subject=str(payload.subject or '').strip(),
            body=str(payload.body or '').strip(),
            context=dict(payload.context or {}),
            metadata=dict(payload.metadata or {}),
        )

        if invalid_recipients:
            detail = f'Invalid email recipient(s): {", ".join(invalid_recipients)}'
            logger.warning(
                'Email notification rejected for event %s due to invalid recipients: %s',
                payload.event,
                ', '.join(invalid_recipients),
            )
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata={
                    'error_message': detail,
                    'provider_response': {
                        'invalid_recipients': invalid_recipients,
                    },
                    'sent_at': None,
                },
            )

        if not normalized_payload.recipients:
            detail = 'Email delivery failed because no valid recipients were provided.'
            logger.warning('Email notification for event %s has no valid recipients.', payload.event)
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata={
                    'error_message': detail,
                    'provider_response': {
                        'invalid_recipients': list(payload.recipients),
                    },
                    'sent_at': None,
                },
            )

        html_body = self._extract_html_body(normalized_payload)
        from_email = str(
            normalized_payload.metadata.get('from_email')
            or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
            or ''
        ).strip()
        timeout = self._resolve_timeout()

        try:
            connection = get_connection(
                backend=getattr(settings, 'EMAIL_BACKEND', None),
                fail_silently=False,
                timeout=timeout,
            )
            message = EmailMultiAlternatives(
                subject=normalized_payload.subject,
                body=normalized_payload.body,
                from_email=from_email or None,
                to=list(normalized_payload.recipients),
                connection=connection,
            )
            if html_body:
                message.attach_alternative(html_body, 'text/html')

            sent_count = message.send(fail_silently=False)
            sent_at = timezone.now().isoformat()
            response = {
                'backend': getattr(settings, 'EMAIL_BACKEND', ''),
                'from_email': from_email,
                'html_included': bool(html_body),
                'sent_count': sent_count,
                'timeout': timeout,
            }

            if sent_count <= 0:
                detail = 'Email backend reported zero sent messages.'
                logger.error(
                    'Email notification for event %s did not send any message to %s.',
                    payload.event,
                    ', '.join(normalized_payload.recipients),
                )
                return self.build_result(
                    payload=normalized_payload,
                    status=NotificationStatus.FAILED,
                    detail=detail,
                    metadata={
                        'error_message': detail,
                        'provider_response': response,
                        'sent_at': None,
                    },
                )

            logger.info(
                'Email notification sent for event %s to %s.',
                payload.event,
                ', '.join(normalized_payload.recipients),
            )
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.SENT,
                detail='Email sent successfully.',
                metadata={
                    'provider_response': response,
                    'sent_at': sent_at,
                },
            )
        except Exception as exc:
            detail = f'{exc.__class__.__name__}: {exc}'
            logger.exception(
                'Email notification failed for event %s to %s.',
                payload.event,
                ', '.join(normalized_payload.recipients),
            )
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata={
                    'error_message': detail,
                    'provider_response': {
                        'backend': getattr(settings, 'EMAIL_BACKEND', ''),
                        'exception_type': exc.__class__.__name__,
                        'from_email': from_email,
                        'html_included': bool(html_body),
                        'timeout': timeout,
                    },
                    'sent_at': None,
                },
            )

    def _extract_html_body(self, payload: NotificationPayload) -> str:
        """Read an optional HTML body from payload metadata or context."""
        candidates = (
            payload.metadata.get('html_body'),
            payload.metadata.get('html_message'),
            payload.context.get('html_body'),
            payload.context.get('html_message'),
        )
        for candidate in candidates:
            value = str(candidate or '').strip()
            if value:
                return value
        return ''

    def _resolve_timeout(self) -> int:
        """Resolve the effective timeout from Django settings."""
        raw_timeout = getattr(settings, 'EMAIL_TIMEOUT', 30) or 30
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError):
            timeout = 30
        return max(timeout, 1)

    def _validate_recipients(self, recipients: list[str]) -> tuple[list[str], list[str]]:
        """Normalize, validate, and de-duplicate email recipients."""
        valid_recipients: list[str] = []
        invalid_recipients: list[str] = []
        seen: set[str] = set()

        for raw_recipient in recipients:
            recipient = str(raw_recipient or '').strip().lower()
            if not recipient:
                continue
            try:
                validate_email(recipient)
            except ValidationError:
                invalid_recipients.append(recipient)
                continue
            if recipient in seen:
                continue
            seen.add(recipient)
            valid_recipients.append(recipient)

        return valid_recipients, invalid_recipients
