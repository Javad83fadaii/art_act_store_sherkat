from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus
from notifications.sms_patterns import SMSPatternDefinition, SMSPatternRegistry

from .base import BaseNotificationProvider, NotificationPayload, NotificationSendResult


logger = logging.getLogger(__name__)


class SMSProvider(BaseNotificationProvider):
    """Send template-based SMS notifications through sms.ir."""

    provider_type = NotificationProviderType.SMS
    channel = NotificationChannel.SMS

    def send(self, payload: NotificationPayload) -> NotificationSendResult:
        valid_recipients, invalid_recipients = self._validate_recipients(payload.recipients)
        normalized_payload = NotificationPayload(
            event=payload.event,
            recipients=valid_recipients,
            subject=str(payload.subject or '').strip(),
            body=str(payload.body or '').strip(),
            context=dict(payload.context or {}),
            metadata=dict(payload.metadata or {}),
        )

        pattern_name = self._resolve_pattern_name(normalized_payload)
        base_metadata = {
            'pattern_name': pattern_name,
            'pattern_code': '',
            'provider_message_id': None,
            'response_code': None,
            'response_body': None,
            'error_message': '',
            'sent_at': None,
            'provider_response': {
                'base_url': self._resolve_base_url(),
                'endpoint': self._resolve_verify_endpoint(),
                'invalid_recipients': invalid_recipients,
                'attempts': [],
                'timeout': self._resolve_timeout(),
            },
        }

        if invalid_recipients:
            logger.warning(
                'SMS notification for event %s ignored invalid recipients: %s',
                payload.event,
                ', '.join(invalid_recipients),
            )

        if not normalized_payload.recipients:
            detail = 'SMS delivery failed because no valid mobile numbers were provided.'
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        if not pattern_name:
            detail = 'SMS delivery failed because no pattern name was provided.'
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        try:
            pattern = SMSPatternRegistry().get(pattern_name)
        except KeyError:
            detail = f'SMS pattern "{pattern_name}" is not configured.'
            logger.warning('SMS pattern lookup failed for event %s: %s', payload.event, pattern_name)
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        base_metadata['pattern_code'] = pattern.code
        if not pattern.code:
            detail = f'SMS pattern "{pattern.name}" does not have a configured code.'
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        missing_variables = self._find_missing_variables(pattern, normalized_payload.context)
        if missing_variables:
            detail = f'SMS pattern "{pattern.name}" is missing required variables: {", ".join(missing_variables)}'
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            metadata['provider_response'] = dict(base_metadata['provider_response'])
            metadata['provider_response']['missing_variables'] = missing_variables
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        api_key = self._resolve_api_key()
        if not api_key:
            detail = 'SMS delivery failed because SMS_IR_API_KEY is not configured.'
            metadata = dict(base_metadata)
            metadata['error_message'] = detail
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        url = f'{self._resolve_base_url()}{self._resolve_verify_endpoint()}'
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-API-KEY': api_key,
        }
        timeout = self._resolve_timeout()
        attempt_results: list[dict[str, Any]] = []
        successful_message_ids: list[Any] = []
        failed_recipients: list[str] = []

        for recipient in normalized_payload.recipients:
            request_payload = self._build_request_payload(pattern, recipient, normalized_payload.context)
            try:
                response = requests.post(
                    url,
                    json=request_payload,
                    headers=headers,
                    timeout=timeout,
                )
                response_body = response.text
                response_data = self._parse_response_body(response)
                response_code = response.status_code
                provider_message_id = self._extract_provider_message_id(response_data)
                sent_at = timezone.now().isoformat() if self._is_success_response(response, response_data) else None

                attempt_results.append(
                    {
                        'mobile': recipient,
                        'request_payload': request_payload,
                        'response_code': response_code,
                        'response_body': response_data if response_data is not None else response_body,
                        'provider_message_id': provider_message_id,
                        'sent_at': sent_at,
                    }
                )

                if self._is_success_response(response, response_data):
                    successful_message_ids.append(provider_message_id)
                else:
                    failed_recipients.append(recipient)
                    logger.error(
                        'sms.ir rejected SMS for event %s to %s with status code %s.',
                        payload.event,
                        recipient,
                        response_code,
                    )
            except requests.RequestException as exc:
                detail = f'{exc.__class__.__name__}: {exc}'
                attempt_results.append(
                    {
                        'mobile': recipient,
                        'request_payload': request_payload,
                        'response_code': None,
                        'response_body': None,
                        'provider_message_id': None,
                        'error_message': detail,
                        'sent_at': None,
                    }
                )
                failed_recipients.append(recipient)
                logger.exception(
                    'sms.ir request failed for event %s to %s.',
                    payload.event,
                    recipient,
                )

        metadata = dict(base_metadata)
        metadata['provider_response'] = dict(base_metadata['provider_response'])
        metadata['provider_response']['attempts'] = attempt_results

        if len(attempt_results) == 1:
            first_attempt = attempt_results[0]
            metadata['provider_message_id'] = first_attempt.get('provider_message_id')
            metadata['response_code'] = first_attempt.get('response_code')
            metadata['response_body'] = first_attempt.get('response_body')
            metadata['sent_at'] = first_attempt.get('sent_at')

        if failed_recipients:
            detail = f'SMS delivery failed for recipient(s): {", ".join(failed_recipients)}'
            metadata['error_message'] = detail
            metadata['provider_response']['failed_recipients'] = failed_recipients
            metadata['provider_response']['successful_message_ids'] = successful_message_ids
            return self.build_result(
                payload=normalized_payload,
                status=NotificationStatus.FAILED,
                detail=detail,
                metadata=metadata,
            )

        metadata['provider_response']['successful_message_ids'] = successful_message_ids
        if attempt_results:
            metadata['sent_at'] = attempt_results[-1].get('sent_at')

        logger.info(
            'SMS notification sent for event %s to %s using pattern %s.',
            payload.event,
            ', '.join(normalized_payload.recipients),
            pattern.name,
        )
        return self.build_result(
            payload=normalized_payload,
            status=NotificationStatus.SENT,
            detail='SMS sent successfully.',
            metadata=metadata,
        )

    def _build_request_payload(
        self,
        pattern: SMSPatternDefinition,
        recipient: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        template_id: int | str = pattern.code
        if str(pattern.code).isdigit():
            template_id = int(pattern.code)

        return {
            'mobile': recipient,
            'templateId': template_id,
            'parameters': [
                {
                    'name': variable,
                    'value': self._stringify_context_value(context.get(variable)),
                }
                for variable in pattern.variables
            ],
        }

    def _extract_provider_message_id(self, response_data: Any) -> Any:
        if isinstance(response_data, dict):
            data = response_data.get('data')
            if isinstance(data, list) and data:
                return data[0]
            return data
        return None

    def _find_missing_variables(
        self,
        pattern: SMSPatternDefinition,
        context: dict[str, Any],
    ) -> list[str]:
        missing: list[str] = []
        for variable in pattern.variables:
            value = context.get(variable)
            if value is None:
                missing.append(variable)
                continue
            if isinstance(value, str) and not value.strip():
                missing.append(variable)
        return missing

    def _is_success_response(self, response: requests.Response, response_data: Any) -> bool:
        if not response.ok:
            return False
        if isinstance(response_data, dict):
            return int(response_data.get('status') or 0) == 1
        return False

    def _parse_response_body(self, response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raw_body = response.text.strip()
            if not raw_body:
                return None
            try:
                return json.loads(raw_body)
            except ValueError:
                return raw_body

    def _resolve_pattern_name(self, payload: NotificationPayload) -> str:
        candidates = (
            payload.metadata.get('sms_pattern'),
            payload.metadata.get('template_key'),
            payload.context.get('sms_pattern'),
            payload.event,
        )
        registry = SMSPatternRegistry()
        for candidate in candidates:
            pattern_name = str(candidate or '').strip()
            if pattern_name and registry.has(pattern_name):
                return pattern_name
        return str(payload.metadata.get('sms_pattern') or payload.metadata.get('template_key') or '').strip()

    def _resolve_api_key(self) -> str:
        return str(getattr(settings, 'SMS_IR_API_KEY', '') or '').strip()

    def _resolve_base_url(self) -> str:
        return str(getattr(settings, 'SMS_IR_BASE_URL', 'https://api.sms.ir') or 'https://api.sms.ir').rstrip('/')

    def _resolve_verify_endpoint(self) -> str:
        endpoint = str(getattr(settings, 'SMS_IR_VERIFY_ENDPOINT', '/v1/send/verify') or '/v1/send/verify').strip()
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        return endpoint

    def _resolve_timeout(self) -> int:
        raw_timeout = getattr(settings, 'SMS_IR_TIMEOUT', 30) or 30
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError):
            timeout = 30
        return max(timeout, 1)

    def _stringify_context_value(self, value: Any) -> str:
        if value is None:
            return ''
        return str(value).strip()

    def _validate_recipients(self, recipients: list[str]) -> tuple[list[str], list[str]]:
        valid_recipients: list[str] = []
        invalid_recipients: list[str] = []
        seen: set[str] = set()

        for raw_recipient in recipients:
            normalized = self._normalize_mobile(raw_recipient)
            if not normalized:
                candidate = str(raw_recipient or '').strip()
                if candidate:
                    invalid_recipients.append(candidate)
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            valid_recipients.append(normalized)

        return valid_recipients, invalid_recipients

    def _normalize_mobile(self, mobile: Any) -> str | None:
        digits = ''.join(character for character in str(mobile or '') if character.isdigit())
        if not digits:
            return None

        if digits.startswith('0098'):
            digits = digits[4:]
        elif digits.startswith('98'):
            digits = digits[2:]
        elif digits.startswith('0'):
            digits = digits[1:]

        if len(digits) == 10 and digits.startswith('9'):
            return digits
        return None
