import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import CustomUser

from .models import Artist, Artwork, VisitHistory, TelegramPurchaseRequest
from .views import _send_telegram_purchase_message


class StoreVisitTrackingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=10, name='هنرمند فروشگاه')
        self.artwork = Artwork.objects.create(
            title='اثر فروشگاهی',
            artist=self.artist,
            description='توضیحات تست',
            price=100000,
        )

    def test_artwork_detail_page_refresh_does_not_track_visit(self):
        response = self.client.get(
            reverse('store:artwork_detail', kwargs={'pk': self.artwork.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(VisitHistory.objects.count(), 0)

    def test_track_visit_endpoint_creates_store_product_visit_only_on_click(self):
        response = self.client.post(
            reverse('track_public_visit'),
            data=json.dumps({'kind': 'store_product', 'object_id': self.artwork.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(VisitHistory.objects.count(), 1)
        visit = VisitHistory.objects.get()
        self.assertEqual(visit.product, self.artwork)


class TelegramPurchaseWebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=11, name='هنرمند تست تلگرام')
        self.user = CustomUser.objects.create_user(
            phone_number='09120000001',
            password='Test@1234',
            full_name='کاربر خرید',
        )
        self.artwork = Artwork.objects.create(
            title='اثر تست تلگرام',
            artist=self.artist,
            description='توضیحات',
            price=250000,
            is_sold=Artwork.IsSoldStatus.RESERVED,
        )
        self.purchase_request = TelegramPurchaseRequest.objects.create(
            user=self.user,
            artwork=self.artwork,
            status='pending',
        )
        self.webhook_url = reverse('store:telegram_purchase_webhook')

    @patch('store.views.requests.post')
    def test_purchase_message_includes_inline_buttons(self, post_mock):
        post_mock.return_value.status_code = 200
        post_mock.return_value.text = 'ok'
        with patch('store.views.BOT_TOKEN', 'test-bot-token'), patch('store.views.ADMIN_GROUP_CHAT_ID', -100100), patch('store.views.MESSAGE_THREAD_ID', 9):
            _send_telegram_purchase_message('پیام تست', purchase_request_id=self.purchase_request.pk)

        self.assertTrue(post_mock.called)
        payload = post_mock.call_args.kwargs['json']
        self.assertIn('reply_markup', payload)
        inline_keyboard = payload['reply_markup']['inline_keyboard']
        self.assertEqual(len(inline_keyboard[0]), 2)
        self.assertEqual(inline_keyboard[0][0]['callback_data'], f'purchase:approve:{self.purchase_request.pk}')
        self.assertEqual(inline_keyboard[0][1]['callback_data'], f'purchase:reject:{self.purchase_request.pk}')

    @patch('store.views.requests.post')
    def test_telegram_webhook_approve_confirms_purchase_and_marks_artwork_sold(self, post_mock):
        post_mock.return_value.status_code = 200
        post_mock.return_value.text = 'ok'
        payload = {
            'callback_query': {
                'id': 'cb-approve',
                'data': f'purchase:approve:{self.purchase_request.pk}',
                'from': {'username': 'admin_user'},
                'message': {
                    'message_id': 101,
                    'message_thread_id': 9,
                    'chat': {'id': -100100},
                },
            }
        }

        with patch('store.views.BOT_TOKEN', 'test-bot-token'), patch('store.views.ADMIN_GROUP_CHAT_ID', -100100), patch('store.views.MESSAGE_THREAD_ID', 9):
            response = self.client.post(
                self.webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.purchase_request.refresh_from_db()
        self.artwork.refresh_from_db()
        self.assertEqual(self.purchase_request.status, 'confirmed')
        self.assertEqual(self.artwork.is_sold, Artwork.IsSoldStatus.SOLD)
        self.assertGreaterEqual(post_mock.call_count, 3)

    @patch('store.views.requests.post')
    def test_telegram_webhook_reject_releases_artwork(self, post_mock):
        post_mock.return_value.status_code = 200
        post_mock.return_value.text = 'ok'
        payload = {
            'callback_query': {
                'id': 'cb-reject',
                'data': f'purchase:reject:{self.purchase_request.pk}',
                'from': {'username': 'admin_user'},
                'message': {
                    'message_id': 102,
                    'message_thread_id': 9,
                    'chat': {'id': -100100},
                },
            }
        }

        with patch('store.views.BOT_TOKEN', 'test-bot-token'), patch('store.views.ADMIN_GROUP_CHAT_ID', -100100), patch('store.views.MESSAGE_THREAD_ID', 9):
            response = self.client.post(
                self.webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.purchase_request.refresh_from_db()
        self.artwork.refresh_from_db()
        self.assertEqual(self.purchase_request.status, 'rejected')
        self.assertEqual(self.artwork.is_sold, Artwork.IsSoldStatus.AVAILABLE)
        self.assertGreaterEqual(post_mock.call_count, 3)
