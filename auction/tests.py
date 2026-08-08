from decimal import Decimal
from datetime import timedelta
import json
from unittest.mock import patch

from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus
from accounts.models import CreditIncreaseRequest, CustomUser
from notifications.models import NotificationDelivery
from notifications.providers import NotificationSendResult
from store.models import Artist, Artwork, ArtworkType, PurchaseHistory

from .models import Auction, AuctionCartItem, AuctionProduct, AuctionVisitHistory
from .signals import schedule_auction_emails
from .tasks import (
    send_auction_ended_email,
    send_auction_started_email,
    send_auction_starting_soon_email,
)


class AuctionBidCreditFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=1, name='هنرمند تست')
        self.artwork_type = ArtworkType.objects.create(name='نقاشی')
        self.auction = Auction.objects.create(
            name='مزایده تست',
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        self.product = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1001',
            title='تابلو تست',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        self.user_one = self._create_verified_user('09120000001', 'کاربر اول', Decimal('1000'))
        self.user_two = self._create_verified_user('09120000002', 'کاربر دوم', Decimal('1000'))

    def _create_verified_user(self, phone_number, full_name, credit):
        user = CustomUser.objects.create_user(
            phone_number=phone_number,
            password='Test@1234',
            full_name=full_name,
        )
        user.is_verified = 1
        user.credit = credit
        user.current_credit = credit
        user.save()
        return user

    def test_first_highest_bid_creates_cart_item_and_deducts_credit(self):
        self.product.place_bid(self.user_one, '200')

        self.user_one.refresh_from_db()
        self.product.refresh_from_db()
        cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(self.user_one.credit, Decimal('1000'))
        self.assertEqual(self.user_one.current_credit, Decimal('800'))
        self.assertEqual(cart_item.user, self.user_one)
        self.assertEqual(cart_item.reserved_amount, Decimal('200'))
        self.assertTrue(cart_item.is_active)
        self.assertEqual(self.product.current_price, Decimal('200'))
        self.assertEqual(self.product.winner, self.user_one)

    def test_outbid_refunds_previous_bidder_and_keeps_previous_cart_item_inactive(self):
        self.product.place_bid(self.user_one, '200')
        self.product.place_bid(self.user_two, '250')

        self.user_one.refresh_from_db()
        self.user_two.refresh_from_db()
        self.product.refresh_from_db()
        active_cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)
        inactive_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product, is_active=False)

        self.assertEqual(self.user_one.credit, Decimal('1000'))
        self.assertEqual(self.user_one.current_credit, Decimal('1000'))
        self.assertEqual(self.user_two.credit, Decimal('1000'))
        self.assertEqual(self.user_two.current_credit, Decimal('750'))
        self.assertEqual(active_cart_item.user, self.user_two)
        self.assertEqual(active_cart_item.reserved_amount, Decimal('250'))
        self.assertEqual(inactive_cart_item.reserved_amount, Decimal('200'))
        self.assertIsNotNone(inactive_cart_item.outbid_at)
        self.assertEqual(self.product.winner, self.user_two)
        self.assertEqual(AuctionCartItem.objects.count(), 2)

    def test_outbid_user_bids_again_updates_same_cart_row(self):
        self.product.place_bid(self.user_one, '200')
        first_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product)

        self.product.place_bid(self.user_two, '250')
        self.product.place_bid(self.user_one, '300')

        self.user_one.refresh_from_db()
        self.user_two.refresh_from_db()
        updated_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product)
        active_cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(first_cart_item.pk, updated_cart_item.pk)
        self.assertEqual(updated_cart_item.reserved_amount, Decimal('300'))
        self.assertTrue(updated_cart_item.is_active)
        self.assertIsNone(updated_cart_item.outbid_at)
        self.assertEqual(active_cart_item.user, self.user_one)
        self.assertEqual(AuctionCartItem.objects.filter(user=self.user_one, product=self.product).count(), 1)
        self.assertEqual(AuctionCartItem.objects.count(), 2)
        self.assertEqual(self.user_one.current_credit, Decimal('700'))
        self.assertEqual(self.user_two.current_credit, Decimal('1000'))

    def test_same_user_raises_bid_only_for_incremental_amount(self):
        self.product.place_bid(self.user_one, '200')
        self.product.place_bid(self.user_one, '260')

        self.user_one.refresh_from_db()
        cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(self.user_one.credit, Decimal('1000'))
        self.assertEqual(self.user_one.current_credit, Decimal('740'))
        self.assertEqual(cart_item.reserved_amount, Decimal('260'))
        self.assertEqual(AuctionCartItem.objects.count(), 1)
        self.assertEqual(self.product.bids.filter(user=self.user_one).count(), 2)

    def test_min_next_bid_uses_current_price_as_percentage_base(self):
        self.assertEqual(self.product.get_min_next_bid(), 110)

        self.product.place_bid(self.user_one, '200')
        self.product.refresh_from_db()

        self.assertEqual(self.product.get_min_next_bid(), 220)

    def test_updating_total_credit_recalculates_current_credit_from_active_cart(self):
        self.product.place_bid(self.user_one, '200')

        self.user_one.refresh_from_db()
        self.user_one.credit = Decimal('1200')
        self.user_one.save(update_fields=['credit'])
        self.user_one.refresh_from_db()

        self.assertEqual(self.user_one.credit, Decimal('1200'))
        self.assertEqual(self.user_one.current_credit, Decimal('1000'))

    def test_finished_auction_releases_reserved_credit(self):
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        self.user_one.refresh_current_credit()
        self.user_one.refresh_from_db()

        self.assertEqual(self.user_one.credit, Decimal('1000'))
        self.assertEqual(self.user_one.current_credit, Decimal('1000'))

    def test_ajax_bid_without_credit_returns_existing_credit_request_state(self):
        self.user_one.credit = Decimal('50')
        self.user_one.save(update_fields=['credit'])
        CreditIncreaseRequest.objects.create(
            user=self.user_one,
            current_credit=Decimal('50'),
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )
        self.client.force_login(self.user_one)

        response = self.client.post(
            reverse('auction:place_bid', kwargs={'pk': self.product.pk}),
            {'amount': '200'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload['needs_credit_increase'])
        self.assertEqual(payload['credit_request_state'], 'pending')
        self.assertEqual(AuctionCartItem.objects.count(), 0)

    def test_ajax_bid_returns_live_payload_for_immediate_ui_update(self):
        self.client.force_login(self.user_one)

        response = self.client.post(
            reverse('auction:place_bid', kwargs={'pk': self.product.pk}),
            {'amount': '200'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['current_price'], 200)
        self.assertEqual(payload['bid_count'], 1)
        self.assertEqual(payload['min_next_bid'], 220)
        self.assertEqual(payload['my_bids_count'], 1)
        self.assertIn('200', payload['my_bids_html'])

    @patch('auction.signals._BID_EMAIL_EXECUTOR.submit')
    def test_bid_email_notifications_are_enqueued_after_commit(self, submit_mock):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.product.place_bid(self.user_one, '200')

        self.assertEqual(len(callbacks), 1)
        submit_mock.assert_called_once()
        submitted_callable, submitted_bid_id = submit_mock.call_args.args
        self.assertEqual(submitted_callable.__name__, '_send_bid_notification_emails')
        self.assertIsInstance(submitted_bid_id, int)

    def test_live_state_endpoint_returns_latest_price_and_history_html(self):
        self.product.place_bid(self.user_one, '200')
        self.client.force_login(self.user_one)

        response = self.client.get(
            reverse('auction:auction_product_live_state', kwargs={'pk': self.product.pk}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['current_price'], 200)
        self.assertEqual(payload['bid_count'], 1)
        self.assertEqual(payload['my_bids_count'], 1)
        self.assertIn('تاریخچه بیدهای شما', payload['my_bids_html'])

    def test_finished_live_state_endpoint_is_public_for_compact_product_cards(self):
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        response = self.client.get(
            reverse('auction:auction_product_live_state', kwargs={'pk': self.product.pk}),
            {'compact': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['current_price'], 220)
        self.assertEqual(payload['bid_count'], 1)
        self.assertTrue(payload['has_winner'])

    def test_profile_shows_active_auction_cart_items(self):
        self.product.place_bid(self.user_one, '200')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'سبد خرید مزایده')
        self.assertContains(response, 'تابلو تست')
        self.assertContains(response, '200')

    def test_profile_shows_outbid_cart_items_as_inactive(self):
        self.product.place_bid(self.user_one, '200')
        self.product.place_bid(self.user_two, '250')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غیرفعال')
        self.assertContains(response, 'دیگر بالاترین پیشنهاد نیست')

    def test_profile_moves_bid_history_into_auction_cart(self):
        self.product.place_bid(self.user_one, '200')
        self.product.place_bid(self.user_one, '220')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تاریخچه بیدهای این محصول')
        self.assertContains(response, '۲۲۰')
        self.assertNotContains(response, 'بیدهای ثبت شده')

    def test_finished_auction_moves_won_product_to_auction_purchases(self):
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خریدهای مزایده')
        self.assertContains(response, 'برنده مزایده')
        self.assertContains(response, 'مزایده‌های گذشته')
        self.assertContains(response, 'این محصول به بخش خریدهای مزایده شما منتقل شده است.')

    def test_profile_separates_store_purchases_from_auction_purchases(self):
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        store_artwork = Artwork.objects.create(
            title='اثر فروشگاه',
            artist=self.artist,
            artwork_type=self.artwork_type,
            description='توضیح تست',
            price=Decimal('500'),
            is_sold=Artwork.IsSoldStatus.SOLD,
        )
        PurchaseHistory.objects.create(user=self.user_one, artwork=store_artwork)
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خریدهای فروشگاه')
        self.assertContains(response, 'خریدهای مزایده')
        self.assertContains(response, 'اثر فروشگاه')
        self.assertContains(response, 'تابلو تست')

    def test_finished_auction_products_page_shows_sold_badge_for_winner(self):
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        response = self.client.get(reverse('auction:auction_products', kwargs={'pk': self.auction.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'به فروش رسید')
        self.assertContains(response, 'data-has-winner="1"')

    def test_auction_products_page_orders_items_by_lot_number(self):
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1002',
            title='محصول لات 10',
            lot=10,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1003',
            title='محصول لات 2',
            lot=2,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1004',
            title='محصول بدون لات',
            lot=None,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )

        response = self.client.get(
            reverse('auction:auction_products', kwargs={'pk': self.auction.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        product_titles = [product.title for product in response.context['products']]
        self.assertEqual(
            product_titles,
            ['محصول لات 2', 'محصول لات 10', 'تابلو تست', 'محصول بدون لات'],
        )

    def test_auction_product_model_default_ordering_uses_lot_number(self):
        AuctionProduct.objects.filter(pk=self.product.pk).update(lot=7)
        self.product.refresh_from_db()
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1005',
            title='محصول لات 3',
            lot=3,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1006',
            title='محصول بدون لات',
            lot=None,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )

        product_titles = list(
            AuctionProduct.objects.filter(auction=self.auction).values_list('title', flat=True)
        )

        self.assertEqual(
            product_titles,
            ['محصول لات 3', 'تابلو تست', 'محصول بدون لات'],
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    @patch('auction.tasks.send_auction_extended_email.delay')
    def test_extending_auction_sends_extension_email_notification(self, extended_email_mock):
        original_end = self.auction.end_date
        self.auction.end_date = original_end + timedelta(hours=2)
        self.auction.save(update_fields=['end_date'])

        extended_email_mock.assert_called_once()
        _, kwargs = extended_email_mock.call_args
        self.assertEqual(kwargs['previous_end'], original_end.isoformat())
        self.assertEqual(kwargs['expected_end'], self.auction.end_date.isoformat())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_send_auction_ended_email_sends_billing_email_to_winner(self):
        self.user_one.email = 'winner@example.com'
        self.user_one.save(update_fields=['email'])
        self.user_two.email = 'other@example.com'
        self.user_two.save(update_fields=['email'])
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        send_auction_ended_email(self.auction.id, expected_end=self.auction.end_date.isoformat())

        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        subjects = [item.subject for item in email_deliveries]
        self.assertIn(f"مزایده «{self.auction.name}» به پایان رسید", subjects)
        self.assertIn(f"نتیجه مزایده و صورتحساب اولیه «{self.auction.name}»", subjects)
        winner_messages = [item for item in email_deliveries if item.recipients == ['winner@example.com']]
        self.assertTrue(winner_messages)
        winner_mail = next(
            item for item in winner_messages
            if item.subject == f"نتیجه مزایده و صورتحساب اولیه «{self.auction.name}»"
        )
        self.assertIn('جمع کل صورتحساب اولیه', winner_mail.body)
        self.assertIn('تابلو تست', winner_mail.body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    @patch('auction.tasks.send_auction_starting_soon_email.apply_async')
    @patch('auction.tasks.send_auction_started_email.apply_async')
    def test_schedule_auction_emails_queues_start_notifications(self, started_mock, starting_soon_mock):
        future_start = timezone.now() + timedelta(hours=30)
        future_end = future_start + timedelta(hours=12)

        auction = Auction.objects.create(
            name='مزایده آینده',
            start_date=future_start,
            end_date=future_end,
            products_count=1,
        )

        starting_soon_mock.assert_called_once()
        _, starting_kwargs = starting_soon_mock.call_args
        self.assertEqual(starting_kwargs['kwargs']['expected_start'], auction.start_date.isoformat())
        self.assertEqual(starting_kwargs['eta'], future_start - timedelta(hours=24))

        started_mock.assert_called_once()
        _, started_kwargs = started_mock.call_args
        self.assertEqual(started_kwargs['kwargs']['expected_start'], auction.start_date.isoformat())
        self.assertEqual(started_kwargs['eta'], future_start)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_send_auction_starting_soon_email_sends_only_near_24h_mark(self):
        self.user_one.email = 'first@example.com'
        self.user_one.save(update_fields=['email'])
        self.user_two.email = 'second@example.com'
        self.user_two.save(update_fields=['email'])

        self.auction.start_date = timezone.now() + timedelta(hours=24, minutes=1)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])
        NotificationDelivery.objects.all().delete()

        send_auction_starting_soon_email(
            self.auction.id,
            expected_start=self.auction.start_date.isoformat(),
        )
        self.assertEqual(NotificationDelivery.objects.count(), 0)

        self.auction.start_date = timezone.now() + timedelta(hours=24)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])
        NotificationDelivery.objects.all().delete()

        send_auction_starting_soon_email(
            self.auction.id,
            expected_start=self.auction.start_date.isoformat(),
        )

        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        self.assertEqual(len(email_deliveries), 2)
        self.assertTrue(all('۲۴ ساعت تا شروع مزایده' in item.subject for item in email_deliveries))
        self.assertEqual(
            {item.recipients[0] for item in email_deliveries},
            {'first@example.com', 'second@example.com'},
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_send_auction_started_email_sends_only_close_to_start_time(self):
        self.user_one.email = 'first@example.com'
        self.user_one.save(update_fields=['email'])

        self.auction.start_date = timezone.now() + timedelta(minutes=10)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])
        NotificationDelivery.objects.all().delete()

        send_auction_started_email(
            self.auction.id,
            expected_start=self.auction.start_date.isoformat(),
        )
        self.assertEqual(NotificationDelivery.objects.count(), 0)

        self.auction.start_date = timezone.now()
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])
        NotificationDelivery.objects.all().delete()

        send_auction_started_email(
            self.auction.id,
            expected_start=self.auction.start_date.isoformat(),
        )

        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        self.assertEqual(len(email_deliveries), 1)
        self.assertIn('مزایده', email_deliveries[0].subject)
        self.assertIn('آغاز شد', email_deliveries[0].subject)

    def test_send_auction_starting_soon_email_respects_user_preferred_contact_methods(self):
        self.user_one.email = 'first@example.com'
        self.user_one.preferred_contact_methods = ['email']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])

        self.user_two.email = 'second@example.com'
        self.user_two.preferred_contact_methods = ['sms']
        self.user_two.save(update_fields=['email', 'preferred_contact_methods'])

        self.auction.start_date = timezone.now() + timedelta(hours=24)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])

        email_res = NotificationSendResult(
            provider=NotificationProviderType.EMAIL,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            recipients=['first@example.com'],
            detail='OK',
        )
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09120000002'],
            detail='OK',
        )

        with patch('notifications.providers.EmailProvider.send', return_value=email_res) as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:
            send_auction_starting_soon_email(
                self.auction.id,
                expected_start=self.auction.start_date.isoformat(),
            )

        self.assertEqual(mock_email_send.call_count, 1)
        self.assertEqual(mock_sms_send.call_count, 1)

    def test_send_auction_started_email_respects_user_preferred_contact_methods(self):
        self.user_one.email = 'first@example.com'
        self.user_one.preferred_contact_methods = ['email']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])

        self.user_two.email = 'second@example.com'
        self.user_two.preferred_contact_methods = ['sms']
        self.user_two.save(update_fields=['email', 'preferred_contact_methods'])

        self.auction.start_date = timezone.now()
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])

        email_res = NotificationSendResult(
            provider=NotificationProviderType.EMAIL,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            recipients=['first@example.com'],
            detail='OK',
        )
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09120000002'],
            detail='OK',
        )

        with patch('notifications.providers.EmailProvider.send', return_value=email_res) as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:
            send_auction_started_email(
                self.auction.id,
                expected_start=self.auction.start_date.isoformat(),
            )

        self.assertEqual(mock_email_send.call_count, 1)
        self.assertEqual(mock_sms_send.call_count, 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_request_middleware_dispatches_due_starting_soon_email_once(self):
        cache.clear()
        self.user_one.email = 'first@example.com'
        self.user_one.save(update_fields=['email'])
        self.user_two.email = 'second@example.com'
        self.user_two.save(update_fields=['email'])

        self.auction.start_date = timezone.now() + timedelta(hours=24)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.save(update_fields=['start_date', 'end_date'])
        NotificationDelivery.objects.all().delete()

        response = self.client.get(reverse('auction:action'))

        self.assertEqual(response.status_code, 200)
        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        self.assertEqual(len(email_deliveries), 2)
        self.assertTrue(all('۲۴ ساعت تا شروع مزایده' in item.subject for item in email_deliveries))

        cache.clear()
        second_response = self.client.get(reverse('auction:action'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(NotificationDelivery.objects.filter(provider='email').count(), 2)
        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.start_reminder_24h_dispatched_at)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_request_middleware_dispatches_due_ended_email_and_billing_once(self):
        cache.clear()
        self.user_one.email = 'winner@example.com'
        self.user_one.save(update_fields=['email'])
        self.user_two.email = 'other@example.com'
        self.user_two.save(update_fields=['email'])
        self.product.place_bid(self.user_one, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])
        NotificationDelivery.objects.all().delete()

        response = self.client.get(reverse('auction:action'))

        self.assertEqual(response.status_code, 200)
        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        subjects = [item.subject for item in email_deliveries]
        self.assertIn(f"مزایده «{self.auction.name}» به پایان رسید", subjects)
        self.assertIn(f"نتیجه مزایده و صورتحساب اولیه «{self.auction.name}»", subjects)

        cache.clear()
        second_response = self.client.get(reverse('auction:action'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            len([item for item in NotificationDelivery.objects.filter(provider='email') if item.subject == f"مزایده «{self.auction.name}» به پایان رسید"]),
            1,
        )
        self.assertEqual(
            len([item for item in NotificationDelivery.objects.filter(provider='email') if item.subject == f"نتیجه مزایده و صورتحساب اولیه «{self.auction.name}»"]),
            1,
        )
        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.end_notice_dispatched_at)
        self.assertIsNotNone(self.auction.winner_billing_dispatched_at)


class AuctionVisitTrackingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=2, name='هنرمند بازدید')
        self.artwork_type = ArtworkType.objects.create(name='مجسمه')
        self.auction = Auction.objects.create(
            name='مزایده بازدید',
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        self.product = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-2001',
            title='اثر بازدید',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )

    def test_auction_products_page_refresh_does_not_track_visit(self):
        response = self.client.get(reverse('auction:auction_products', kwargs={'pk': self.auction.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuctionVisitHistory.objects.count(), 0)

    def test_track_visit_endpoint_creates_auction_visit_only_on_click(self):
        response = self.client.post(
            reverse('track_public_visit'),
            data=json.dumps({'kind': 'auction', 'object_id': self.auction.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuctionVisitHistory.objects.count(), 1)
        visit = AuctionVisitHistory.objects.get()
        self.assertEqual(visit.auction, self.auction)
        self.assertIsNone(visit.product)

    def test_auction_list_page_marks_auction_links_for_guarded_visit_tracking(self):
        response = self.client.get(reverse('auction:action'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(reverse('auction:auction_products', kwargs={'pk': self.auction.pk}), html)
        self.assertNotIn('href="javascript:void(0);"', html)
        self.assertIn('data-track-visit="1"', html)
        self.assertIn('data-track-guard="auction-access"', html)

    def test_auction_product_detail_page_refresh_does_not_track_visit(self):
        response = self.client.get(reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AuctionVisitHistory.objects.count(), 0)

    def test_finished_auction_product_detail_is_public_without_bid_submission(self):
        winner = CustomUser.objects.create_user(
            phone_number='09120000111',
            password='Test@1234',
            full_name='برنده مزایده',
        )
        winner.is_verified = 1
        winner.credit = Decimal('1000')
        winner.current_credit = Decimal('1000')
        winner.save()

        self.product.place_bid(winner, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        response = self.client.get(
            reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مزایده این اثر به پایان رسیده است')
        self.assertContains(response, 'این اثر دارای برنده نهایی است.')
        self.assertNotContains(response, 'این صفحه برای مشاهده عمومی باز است و ثبت بید غیرفعال شده است.')
        self.assertNotContains(response, 'id="bid-submit-form"', html=False)
        self.assertNotContains(response, 'ورود جهت ثبت پیشنهاد')

    def test_auction_products_page_marks_product_detail_links_for_guarded_visit_tracking(self):
        response = self.client.get(
            reverse('auction:auction_products', kwargs={'pk': self.auction.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk}), html)
        self.assertIn('data-auction-product-link="1"', html)
        self.assertIn('data-auction-quick-bid="1"', html)
        self.assertIn('data-login-message="برای مشاهده جزئیات محصول مزایده، لطفاً ابتدا وارد حساب کاربری خود شوید."', html)
        self.assertIn('data-track-kind="auction_product"', html)
        self.assertIn('data-track-guard="auction-access"', html)
        self.assertIn('data-product-image-link="1"', html)

    def test_finished_auction_products_page_allows_public_product_navigation_script(self):
        winner = CustomUser.objects.create_user(
            phone_number='09120000112',
            password='Test@1234',
            full_name='برنده مزایده عمومی',
        )
        winner.is_verified = 1
        winner.credit = Decimal('1000')
        winner.current_credit = Decimal('1000')
        winner.save()

        self.product.place_bid(winner, '200')
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])

        response = self.client.get(
            reverse('auction:auction_products', kwargs={'pk': self.auction.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('window.canTrackAuctionVisit = function(link)', html)
        self.assertIn("link.dataset.trackKind === 'auction_product'", html)
        self.assertIn('if (canViewAuctionProductDetails()) return;', html)

    def test_track_visit_endpoint_creates_auction_product_visit_only_on_click(self):
        response = self.client.post(
            reverse('track_public_visit'),
            data=json.dumps({'kind': 'auction_product', 'object_id': self.product.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuctionVisitHistory.objects.count(), 1)
        visit = AuctionVisitHistory.objects.get()
        self.assertEqual(visit.auction, self.auction)
        self.assertEqual(visit.product, self.product)

    def test_home_page_marks_active_auction_links_for_guarded_visit_tracking(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(reverse('auction:auction_products', kwargs={'pk': self.auction.pk}), html)
        self.assertIn('data-track-guard="auction-access"', html)
