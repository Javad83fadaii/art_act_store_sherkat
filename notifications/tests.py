from __future__ import annotations

from unittest.mock import patch

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
