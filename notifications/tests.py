from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus
from notifications.models import NotificationDelivery
from notifications.providers import NotificationSendResult
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
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='Auction Platform <sender@example.com>',
    SMS_IR_API_KEY='test-api-key',
    SMS_IR_BASE_URL='https://api.sms.ir',
    SMS_IR_VERIFY_ENDPOINT='/v1/send/verify',
    SMS_IR_TIMEOUT=9,
    SMS_PATTERNS={
        'verification': {
            'code': '210072',
            'variables': ('CODE',),
        },
        'auction_started': {
            'code': '901013',
            'variables': (
                'AUCTIONNAME',
            ),
        },
        'auction_24h': {
            'code': '962018',
            'variables': (
                'AUCTIONNAME',
                'AUCTIONSTART_DATE',
            ),
        },
        'auction_end': {
            'code': '174933',
            'variables': (
                'AUCTIONNAME',
                'NAME',
                'AUCTIONEND_DATE',
            ),
        },
    },
)
class SMSProviderIntegrationTests(TestCase):
    """Exercise the SMS provider against mocked sms.ir responses."""

    def setUp(self) -> None:
        mail.outbox = []
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
                'templateId': 210072,
                'parameters': [
                    {
                        'name': 'CODE',
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
        self.assertEqual(delivery.metadata['pattern_code'], '210072')
        self.assertEqual(delivery.metadata['provider_message_id'], 778899)
        self.assertEqual(delivery.metadata['response_code'], 200)
        self.assertEqual(delivery.metadata['response_body']['status'], 1)
        self.assertTrue(delivery.metadata['sent_at'])

    @patch('notifications.providers.sms.requests.post')
    def test_send_template_maps_verification_code_context_to_sms_ir_code_variable(self, post_mock) -> None:
        """Verification template should map lowercase project context to sms.ir's uppercase variable."""
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

        self.service.send_template(
            template='verification',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'code': '123456',
            },
        )

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 210072,
                'parameters': [
                    {
                        'name': 'CODE',
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

    @patch('notifications.providers.sms.requests.post')
    def test_send_template_maps_auction_started_context_to_sms_pattern_variables(self, post_mock) -> None:
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

        self.service.send_template(
            template='auction_started',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'auction_name': 'مزایده تابستان',
            },
        )

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 901013,
                'parameters': [
                    {
                        'name': 'AUCTIONNAME',
                        'value': 'مزایده تابستان',
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

    @patch('notifications.providers.sms.requests.post')
    def test_send_template_maps_auction_24h_context_to_sms_pattern_variables(self, post_mock) -> None:
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

        self.service.send_template(
            template='auction_24h',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'auction_name': 'مزایده تابستان',
                'auction_start_date': '1405/05/10 18:00',
            },
        )

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 962018,
                'parameters': [
                    {
                        'name': 'AUCTIONNAME',
                        'value': 'مزایده تابستان',
                    },
                    {
                        'name': 'AUCTIONSTART_DATE',
                        'value': '1405/05/10 18:00',
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

    @patch('notifications.providers.sms.requests.post')
    def test_send_template_maps_auction_end_context_to_sms_pattern_variables(self, post_mock) -> None:
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

        self.service.send_template(
            template='auction_end',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'auction_name': 'مزایده تابستان',
                'name': 'علی رضایی',
                'auction_end_date': '1405/05/10 18:00',
            },
        )

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 174933,
                'parameters': [
                    {
                        'name': 'AUCTIONNAME',
                        'value': 'مزایده تابستان',
                    },
                    {
                        'name': 'NAME',
                        'value': 'علی رضایی',
                    },
                    {
                        'name': 'AUCTIONEND_DATE',
                        'value': '1405/05/10 18:00',
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
            context={},
        )

        self.assertEqual(len(result.results), 1)
        provider_result = result.results[0]
        self.assertEqual(provider_result.status, NotificationStatus.FAILED)
        self.assertIn('AUCTIONNAME', provider_result.detail)
        post_mock.assert_not_called()

        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.status, 'failed')
        self.assertEqual(
            delivery.metadata['provider_response']['missing_variables'],
            ['AUCTIONNAME'],
        )

    @patch('notifications.providers.sms.logger.error')
    @patch('notifications.providers.sms.requests.post')
    def test_sms_provider_logs_sms_ir_response_message_on_http_failure(self, post_mock, logger_error_mock) -> None:
        """HTTP failures should log sms.ir's response message for faster diagnosis."""
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.text = '{"status": 12, "message": "کلید وب سرویس محدود به آی پی های تعریف شده می باشد"}'
        response.json.return_value = {
            'status': 12,
            'message': 'کلید وب سرویس محدود به آی پی های تعریف شده می باشد',
            'data': None,
        }
        post_mock.return_value = response

        result = self.service.send_template(
            template='verification',
            channels=['sms'],
            user=SimpleNamespace(phone_number='09123456789'),
            context={
                'code': '123456',
            },
        )

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].status, NotificationStatus.FAILED)
        logger_error_mock.assert_called_once()
        logged_args = logger_error_mock.call_args[0]
        self.assertEqual(logged_args[0], 'sms.ir rejected SMS for event %s to %s with status code %s. Response: %s')
        self.assertEqual(logged_args[1], 'verification')
        self.assertEqual(logged_args[2], '9123456789')
        self.assertEqual(logged_args[3], 401)
        self.assertIn('کلید وب سرویس محدود', logged_args[4])

    @patch('notifications.providers.sms.requests.post')
    def test_send_template_uses_central_registry_for_all_channels(self, post_mock) -> None:
        """Template registry should resolve per-channel content from one template key."""
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
            template='auction_started',
            user=SimpleNamespace(
                phone_number='09123456789',
                email='Receiver@example.com',
                telegram_id='998877',
            ),
            context={
                'auction_name': 'حراج تابستان',
            },
        )

        self.assertEqual(len(result.results), 3)
        self.assertEqual(
            [item.provider for item in result.results],
            [
                NotificationProviderType.EMAIL,
                NotificationProviderType.SMS,
                NotificationProviderType.TELEGRAM,
            ],
        )
        self.assertEqual(result.results[0].status, NotificationStatus.SENT)
        self.assertEqual(result.results[1].status, NotificationStatus.SENT)
        self.assertEqual(result.results[2].status, NotificationStatus.SKIPPED)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['receiver@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'زمان رقابت فرا رسید؛ مزایده حراج تابستان آغاز شد')
        self.assertIn('مزایده حراج تابستان هم\u200cاکنون آغاز شده است.', mail.outbox[0].body)

        post_mock.assert_called_once_with(
            'https://api.sms.ir/v1/send/verify',
            json={
                'mobile': '9123456789',
                'templateId': 901013,
                'parameters': [
                    {
                        'name': 'AUCTIONNAME',
                        'value': 'حراج تابستان',
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


class NotificationDispatcherUserSettingsTests(TestCase):
    """Verify NotificationDispatcher respects user notification channel settings."""

    def setUp(self) -> None:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            phone_number='09129998877',
            password='Password123!',
            full_name='کاربر تست',
            email='testuser@example.com',
        )

    def test_dispatcher_sends_email_only_when_user_selected_email(self) -> None:
        """When user only selected email, dispatcher should invoke only EmailProvider."""
        self.user.preferred_contact_methods = ['email']
        self.user.save()

        service = NotificationService()
        email_res = NotificationSendResult(
            provider=NotificationProviderType.EMAIL,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            recipients=['testuser@example.com'],
            detail='OK',
        )
        with patch('notifications.providers.EmailProvider.send', return_value=email_res) as mock_email_send, \
             patch('notifications.providers.SMSProvider.send') as mock_sms_send:

            service.send(
                event='test.event',
                recipients=['testuser@example.com'],
                subject='تست',
                body='متن تست',
                providers=[NotificationProviderType.EMAIL, NotificationProviderType.SMS],
                context={'user': self.user},
            )

            self.assertEqual(mock_email_send.call_count, 1)
            mock_sms_send.assert_not_called()

    def test_dispatcher_sends_sms_only_when_user_selected_sms(self) -> None:
        """When user only selected SMS, dispatcher should invoke only SMSProvider."""
        self.user.preferred_contact_methods = ['sms']
        self.user.save()

        service = NotificationService()
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09129998877'],
            detail='OK',
        )
        with patch('notifications.providers.EmailProvider.send') as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:

            service.send(
                event='test.event',
                recipients=['09129998877'],
                subject='تست',
                body='متن تست',
                providers=[NotificationProviderType.EMAIL, NotificationProviderType.SMS],
                context={'user': self.user},
            )

            mock_email_send.assert_not_called()
            self.assertEqual(mock_sms_send.call_count, 1)

    def test_dispatcher_sends_both_when_user_selected_both(self) -> None:
        """When user selected both email and SMS, dispatcher should invoke both providers."""
        self.user.preferred_contact_methods = ['email', 'sms']
        self.user.save()

        service = NotificationService()
        email_res = NotificationSendResult(
            provider=NotificationProviderType.EMAIL,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            recipients=['testuser@example.com'],
            detail='OK',
        )
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09129998877'],
            detail='OK',
        )
        with patch('notifications.providers.EmailProvider.send', return_value=email_res) as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:

            service.send(
                event='test.event',
                recipients=['testuser@example.com', '09129998877'],
                subject='تست',
                body='متن تست',
                providers=[NotificationProviderType.EMAIL, NotificationProviderType.SMS],
                context={'user': self.user},
            )

            self.assertEqual(mock_email_send.call_count, 1)
            self.assertEqual(mock_sms_send.call_count, 1)

    def test_dispatcher_fallback_when_user_has_no_settings(self) -> None:
        """When user has no settings specified, default project providers behavior is preserved."""
        self.user.preferred_contact_methods = []
        self.user.save()

        service = NotificationService()
        email_res = NotificationSendResult(
            provider=NotificationProviderType.EMAIL,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            recipients=['testuser@example.com'],
            detail='OK',
        )
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09129998877'],
            detail='OK',
        )
        with patch('notifications.providers.EmailProvider.send', return_value=email_res) as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:

            service.send(
                event='test.event',
                recipients=['testuser@example.com', '09129998877'],
                subject='تست',
                body='متن تست',
                providers=[NotificationProviderType.EMAIL, NotificationProviderType.SMS],
                context={'user': self.user},
            )

            self.assertEqual(mock_email_send.call_count, 1)
            self.assertEqual(mock_sms_send.call_count, 1)

