from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from notifications.enums import NotificationProviderType, NotificationStatus
from notifications.models import NotificationDelivery
from notifications.services import NotificationService, send_notification_safely


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='Auction Platform <sender@example.com>',
    SERVER_EMAIL='sender@example.com',
    EMAIL_TIMEOUT=12,
)
class EmailProviderIntegrationTests(TestCase):
    """Exercise the real email provider against Django's email backend."""

    def setUp(self) -> None:
        mail.outbox = []
        self.service = NotificationService()

    def test_email_provider_sends_plain_and_html_content(self) -> None:
        """Email provider should send both plain text and optional HTML content."""
        result = self.service.send(
            event='notifications.email.test',
            recipients=['Receiver@example.com', 'receiver@example.com'],
            subject='موضوع تست',
            body='نسخه متنی پیام',
            providers=[NotificationProviderType.EMAIL],
            metadata={
                'html_body': '<p>نسخه HTML پیام</p>',
            },
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.SENT)
        self.assertEqual(list(provider_result.recipients), ['receiver@example.com'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['receiver@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'موضوع تست')
        self.assertEqual(mail.outbox[0].body, 'نسخه متنی پیام')
        self.assertEqual(mail.outbox[0].alternatives, [('<p>نسخه HTML پیام</p>', 'text/html')])

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.provider, 'email')
        self.assertEqual(delivery.recipients, ['receiver@example.com'])
        self.assertEqual(delivery.subject, 'موضوع تست')
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(delivery.metadata['provider_response']['sent_count'], 1)
        self.assertEqual(delivery.metadata['provider_response']['timeout'], 12)
        self.assertTrue(delivery.metadata['provider_response']['html_included'])
        self.assertTrue(delivery.metadata['sent_at'])

    def test_email_provider_fails_for_invalid_recipient(self) -> None:
        """Email provider should fail fast when recipients are invalid."""
        result = self.service.send(
            event='notifications.email.invalid',
            recipients=['invalid-recipient'],
            subject='موضوع تست',
            body='متن تست',
            providers=[NotificationProviderType.EMAIL],
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.FAILED)
        self.assertIn('Invalid email recipient', provider_result.detail)
        self.assertEqual(len(mail.outbox), 0)

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.provider, 'email')
        self.assertEqual(delivery.status, 'failed')
        self.assertEqual(delivery.recipients, [])
        self.assertIn('invalid-recipient', delivery.detail)
        self.assertEqual(delivery.metadata['provider_response']['invalid_recipients'], ['invalid-recipient'])
        self.assertIsNone(delivery.metadata['sent_at'])


@override_settings(
    SMS_IR_API_KEY='test-api-key',
    SMS_IR_BASE_URL='https://api.sms.ir',
    SMS_IR_VERIFY_ENDPOINT='/v1/send/verify',
    SMS_IR_TIMEOUT=9,
    SMS_PATTERNS={
        'verification': {
            'code': '100001',
            'variables': ('code',),
        },
        'auction_started': {
            'code': '901013',
            'variables': (
                'first_name',
                'auction_name',
            ),
        },
    },
)
class SMSProviderIntegrationTests(TestCase):
    """Exercise the SMS provider against mocked sms.ir responses."""

    def setUp(self) -> None:
        self.service = NotificationService()

    @patch('notifications.providers.sms.requests.post')
    def test_sms_provider_sends_pattern_message_and_logs_delivery(self, post_mock) -> None:
        """SMS provider should send a verify request to sms.ir and persist provider metadata."""
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response.json.return_value = {
            'status': 1,
            'message': 'موفق',
            'data': 778899,
        }
        post_mock.return_value = response

        result = self.service.send_template(
            template='verification',
            channels=['sms'],
            user=SimpleNamespace(phone_number='+98 912 345 6789'),
            context={
                'code': '123456',
            },
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.SENT)
        self.assertEqual(list(provider_result.recipients), ['9123456789'])

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 100001,
                'parameters': [
                    {
                        'name': 'code',
                        'value': '123456',
                    },
                ],
            },
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-API-KEY': 'test-api-key',
            },
            timeout=9,
        )

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.provider, 'sms')
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(delivery.recipients, ['9123456789'])
        self.assertEqual(delivery.metadata['pattern_name'], 'verification')
        self.assertEqual(delivery.metadata['pattern_code'], '100001')
        self.assertEqual(delivery.metadata['provider_message_id'], 778899)
        self.assertEqual(delivery.metadata['response_code'], 200)
        self.assertEqual(delivery.metadata['response_body']['status'], 1)
        self.assertTrue(delivery.metadata['sent_at'])

    @patch('notifications.providers.sms.requests.post')
    def test_sms_provider_fails_when_pattern_is_missing(self, post_mock) -> None:
        """SMS provider should return a failed result when the requested pattern is unknown."""
        result = self.service.send_template(
            template='missing_pattern',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'code': '123456',
            },
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.FAILED)
        self.assertIn('missing_pattern', provider_result.detail)
        post_mock.assert_not_called()

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.provider, 'sms')
        self.assertEqual(delivery.status, 'failed')
        self.assertEqual(delivery.metadata['pattern_name'], 'missing_pattern')
        self.assertIn('missing_pattern', delivery.metadata['error_message'])

    @patch('notifications.providers.sms.requests.post')
    def test_sms_provider_fails_when_required_variables_are_missing(self, post_mock) -> None:
        """SMS provider should list missing pattern variables before calling sms.ir."""
        result = self.service.send_template(
            template='auction_started',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'first_name': 'علی',
            },
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.FAILED)
        self.assertIn('auction_name', provider_result.detail)
        post_mock.assert_not_called()

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.status, 'failed')
        self.assertEqual(
            delivery.metadata['provider_response']['missing_variables'],
            ['auction_name'],
        )


class NotificationSafeDispatchTests(SimpleTestCase):
    """Verify safe dispatch wiring around Celery tasks."""

    @patch('notifications.services._run_notification_task')
    @patch('notifications.services._can_use_celery_tasks', return_value=True)
    def test_send_notification_safely_uses_task_when_celery_exists(
        self,
        _can_use_celery_tasks_mock,
        run_notification_task_mock,
    ) -> None:
        """send_notification_safely should dispatch through the notification task."""
        send_notification_safely(
            event='notifications.email.safe',
            recipients=['receiver@example.com'],
            subject='موضوع',
            body='متن',
            providers=[NotificationProviderType.EMAIL],
            metadata={'source': 'test'},
        )

        run_notification_task_mock.assert_called_once_with(
            event='notifications.email.safe',
            recipients=['receiver@example.com'],
            subject='موضوع',
            body='متن',
            providers=[NotificationProviderType.EMAIL],
            context=None,
            metadata={'source': 'test'},
        )
