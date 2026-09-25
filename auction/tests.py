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

from .models import (
    Auction,
    AuctionCartItem,
    AuctionProduct,
    AuctionVisitHistory,
    Bid,
    AuctionInvoice,
    AuctionInvoiceItem,
)
from .signals import _send_bid_notification_emails, schedule_auction_emails
from .tasks import (
    send_auction_ended_email,
    send_auction_extended_notice_sms,
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
            base_price=Decimal('10000000'),
        )
        self.user_one = self._create_verified_user('09120000001', 'کاربر اول', Decimal('100000000'))
        self.user_two = self._create_verified_user('09120000002', 'کاربر دوم', Decimal('100000000'))

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
        self.product.place_bid(self.user_one, '20000000')

        self.user_one.refresh_from_db()
        self.product.refresh_from_db()
        cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(self.user_one.credit, Decimal('100000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('80000000'))
        self.assertEqual(cart_item.user, self.user_one)
        self.assertEqual(cart_item.reserved_amount, Decimal('20000000'))
        self.assertTrue(cart_item.is_active)
        self.assertEqual(self.product.current_price, Decimal('20000000'))
        self.assertEqual(self.product.winner, self.user_one)

    def test_outbid_refunds_previous_bidder_and_keeps_previous_cart_item_inactive(self):
        self.product.place_bid(self.user_one, '20000000')
        self.product.place_bid(self.user_two, '25000000')

        self.user_one.refresh_from_db()
        self.user_two.refresh_from_db()
        self.product.refresh_from_db()
        active_cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)
        inactive_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product, is_active=False)

        self.assertEqual(self.user_one.credit, Decimal('100000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('100000000'))
        self.assertEqual(self.user_two.credit, Decimal('100000000'))
        self.assertEqual(self.user_two.current_credit, Decimal('75000000'))
        self.assertEqual(active_cart_item.user, self.user_two)
        self.assertEqual(active_cart_item.reserved_amount, Decimal('25000000'))
        self.assertEqual(inactive_cart_item.reserved_amount, Decimal('20000000'))
        self.assertIsNotNone(inactive_cart_item.outbid_at)
        self.assertEqual(self.product.winner, self.user_two)
        self.assertEqual(AuctionCartItem.objects.count(), 2)

    def test_outbid_user_bids_again_updates_same_cart_row(self):
        self.product.place_bid(self.user_one, '20000000')
        first_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product)

        self.product.place_bid(self.user_two, '25000000')
        self.product.place_bid(self.user_one, '30000000')

        self.user_one.refresh_from_db()
        self.user_two.refresh_from_db()
        updated_cart_item = AuctionCartItem.objects.get(user=self.user_one, product=self.product)
        active_cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(first_cart_item.pk, updated_cart_item.pk)
        self.assertEqual(updated_cart_item.reserved_amount, Decimal('30000000'))
        self.assertTrue(updated_cart_item.is_active)
        self.assertIsNone(updated_cart_item.outbid_at)
        self.assertEqual(active_cart_item.user, self.user_one)
        self.assertEqual(AuctionCartItem.objects.filter(user=self.user_one, product=self.product).count(), 1)
        self.assertEqual(AuctionCartItem.objects.count(), 2)
        self.assertEqual(self.user_one.current_credit, Decimal('70000000'))
        self.assertEqual(self.user_two.current_credit, Decimal('100000000'))

    def test_same_user_raises_bid_only_for_incremental_amount(self):
        self.product.place_bid(self.user_one, '20000000')
        self.product.place_bid(self.user_one, '25000000')

        self.user_one.refresh_from_db()
        cart_item = AuctionCartItem.objects.get(product=self.product, is_active=True)

        self.assertEqual(self.user_one.credit, Decimal('100000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('75000000'))
        self.assertEqual(cart_item.reserved_amount, Decimal('25000000'))
        self.assertEqual(AuctionCartItem.objects.count(), 1)
        self.assertEqual(self.product.bids.filter(user=self.user_one).count(), 2)

    def test_tiered_increments_and_min_next_bid(self):
        # پله ۱: تا سقف ۵۰ میلیون -> افزایش ۵ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('0')), 5000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('45000000')), 5000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('49999999')), 5000000)
        self.assertEqual(self.product.get_min_next_bid(), 15000000)  # base_price 10M + 5M

        # پله ۲: از ۵۰ میلیون تا ۲۰۰ میلیون -> افزایش ۱۰ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('50000000')), 10000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('100000000')), 10000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('199999999')), 10000000)

        # پله ۳: از ۲۰۰ میلیون تا ۵۰۰ میلیون -> افزایش ۲۰ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('200000000')), 20000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('350000000')), 20000000)

        # پله ۴: از ۵۰۰ میلیون تا ۱ میلیارد -> افزایش ۵۰ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('500000000')), 50000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('800000000')), 50000000)

        # پله ۵: از ۱ میلیارد تا ۴ میلیارد -> افزایش ۱۰۰ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('1000000000')), 100000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('2500000000')), 100000000)

        # پله ۶: از ۴ میلیارد به بالا -> افزایش ۲۰۰ میلیون
        self.assertEqual(self.product.get_current_step_increment(Decimal('4000000000')), 200000000)
        self.assertEqual(self.product.get_current_step_increment(Decimal('10000000000')), 200000000)

        # ثبت بید جدید در پله ۱ و ارزیابی حداقل پیشنهاد بعدی
        self.product.place_bid(self.user_one, '20000000')
        self.product.refresh_from_db()
        self.assertEqual(self.product.get_min_next_bid(), 25000000)

    def test_updating_total_credit_recalculates_current_credit_from_active_cart(self):
        self.product.place_bid(self.user_one, '20000000')

        self.user_one.refresh_from_db()
        self.user_one.credit = Decimal('120000000')
        self.user_one.save(update_fields=['credit'])
        self.user_one.refresh_from_db()

        self.assertEqual(self.user_one.credit, Decimal('120000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('100000000'))

    def test_finished_auction_releases_reserved_credit(self):
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
        self.auction.save(update_fields=['end_date'])

        self.user_one.refresh_current_credit()
        self.user_one.refresh_from_db()

        self.assertEqual(self.user_one.credit, Decimal('100000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('100000000'))

    def test_ajax_bid_without_credit_returns_existing_credit_request_state(self):
        self.user_one.credit = Decimal('5000000')
        self.user_one.save(update_fields=['credit'])
        CreditIncreaseRequest.objects.create(
            user=self.user_one,
            current_credit=Decimal('5000000'),
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )
        self.client.force_login(self.user_one)

        response = self.client.post(
            reverse('auction:place_bid', kwargs={'pk': self.product.pk}),
            {'amount': '20000000'},
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
            {'amount': '20000000'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['current_price'], 20000000)
        self.assertEqual(payload['step_increment'], 5000000)
        self.assertEqual(payload['min_next_bid'], 25000000)
        self.assertEqual(payload['bid_count'], 1)
        self.assertEqual(payload['my_bids_count'], 1)
        self.assertIn('200', payload['my_bids_html'])

    @patch('auction.signals._BID_EMAIL_EXECUTOR.submit')
    def test_bid_email_notifications_are_enqueued_after_commit(self, submit_mock):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.product.place_bid(self.user_one, '20000000')

        self.assertEqual(len(callbacks), 1)
        submit_mock.assert_called_once()
        submitted_callable, submitted_bid_id = submit_mock.call_args.args
        self.assertEqual(submitted_callable.__name__, '_send_bid_notification_emails')
        self.assertIsInstance(submitted_bid_id, int)

    def test_bid_confirmation_notifications_send_add_bid_sms_for_sms_only_user(self):
        self.user_one.email = ''
        self.user_one.preferred_contact_methods = ['sms']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])

        created_bid = self.product.place_bid(self.user_one, '20000000')

        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09120000001'],
            detail='OK',
        )

        with patch('notifications.providers.EmailProvider.send') as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:
            _send_bid_notification_emails(created_bid.pk)

        mock_email_send.assert_not_called()
        mock_sms_send.assert_called_once()
        sms_payload = mock_sms_send.call_args.args[0]
        self.assertEqual(sms_payload.event, 'auction.bid.confirmed')
        self.assertEqual(sms_payload.metadata['sms_pattern'], 'add_bid')
        self.assertEqual(sms_payload.context['NAME'], self.user_one.full_name)
        self.assertEqual(sms_payload.context['PRODUCT_TITLE'], self.product.title)

    def test_outbid_notifications_send_dell_bid_sms_for_sms_only_user(self):
        self.user_one.email = ''
        self.user_one.preferred_contact_methods = ['sms']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])
        self.user_two.email = ''
        self.user_two.save(update_fields=['email'])

        self.product.place_bid(self.user_one, '20000000')
        latest_bid = self.product.place_bid(self.user_two, '25000000')

        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09120000001'],
            detail='OK',
        )

        with patch('notifications.providers.EmailProvider.send') as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:
            _send_bid_notification_emails(latest_bid.pk)

        mock_email_send.assert_not_called()
        self.assertEqual(mock_sms_send.call_count, 2)
        sms_payload = mock_sms_send.call_args_list[1].args[0]
        self.assertEqual(sms_payload.event, 'auction.bid.outbid')
        self.assertEqual(sms_payload.metadata['sms_pattern'], 'dell_bid')
        self.assertEqual(sms_payload.context['NAME'], self.user_one.full_name)
        self.assertEqual(sms_payload.context['PRODUCT_TITLE'], self.product.title)

    def test_live_state_endpoint_returns_latest_price_and_history_html(self):
        self.product.place_bid(self.user_one, '20000000')
        self.client.force_login(self.user_one)

        response = self.client.get(
            reverse('auction:auction_product_live_state', kwargs={'pk': self.product.pk}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['current_price'], 20000000)
        self.assertEqual(payload['step_increment'], 5000000)
        self.assertEqual(payload['min_next_bid'], 25000000)
        self.assertEqual(payload['bid_count'], 1)
        self.assertEqual(payload['my_bids_count'], 1)
        self.assertIn('تاریخچه بیدهای شما', payload['my_bids_html'])

    def test_auction_product_pure_price_tax_amount_and_final_price_with_tax(self):
        # بررسی مقادیر بدون بید (بر پایه base_price = 10000000)
        self.assertEqual(self.product.pure_price, Decimal('10000000'))
        self.assertEqual(self.product.tax_amount, Decimal('1000000'))
        self.assertEqual(self.product.final_price_with_tax, Decimal('11000000'))

        # بررسی با ثبت بید 25000000
        self.product.place_bid(self.user_one, '25000000')
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_price, Decimal('25000000'))
        self.assertEqual(self.product.pure_price, Decimal('25000000'))
        self.assertEqual(self.product.tax_amount, Decimal('2500000'))
        self.assertEqual(self.product.final_price_with_tax, Decimal('27500000'))

    def test_finished_live_state_endpoint_is_public_for_compact_product_cards(self):
        self.product.place_bid(self.user_one, '20000000')
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
        self.assertEqual(payload['current_price'], 20000000)
        self.assertEqual(payload['bid_count'], 1)
        self.assertTrue(payload['has_winner'])

    def test_profile_shows_active_auction_cart_items(self):
        self.product.place_bid(self.user_one, '20000000')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'سبد خرید مزایده')
        self.assertContains(response, 'تابلو تست')

    def test_profile_shows_outbid_cart_items_as_inactive(self):
        self.product.place_bid(self.user_one, '20000000')
        self.product.place_bid(self.user_two, '25000000')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غیرفعال')
        self.assertContains(response, 'دیگر بالاترین پیشنهاد نیست')

    def test_profile_moves_bid_history_into_auction_cart(self):
        self.product.place_bid(self.user_one, '20000000')
        self.product.place_bid(self.user_one, '25000000')
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تاریخچه بیدهای این محصول')
        self.assertNotContains(response, 'بیدهای ثبت شده')

    def test_finished_auction_moves_won_product_to_auction_purchases(self):
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
        self.auction.save(update_fields=['end_date'])
        self.client.force_login(self.user_one)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خریدهای مزایده')
        self.assertContains(response, 'برنده مزایده')
        self.assertContains(response, 'مزایده‌های گذشته')
        self.assertContains(response, 'این محصول به بخش خریدهای مزایده شما منتقل شده است.')

    def test_extended_auction_keeps_reserved_credit_and_stays_in_cart(self):
        self.product.place_bid(self.user_one, '20000000')
        # پایان رسمی مزایده سپری شده است
        self.auction.end_date = timezone.now() - timedelta(seconds=1)
        self.auction.save(update_fields=['end_date'])
        # اما اثر تمدید شده و همچنان فعال است
        self.product.extended_end_time = timezone.now() + timedelta(hours=5)
        self.product.save(update_fields=['extended_end_time'])

        self.user_one.refresh_current_credit()
        self.user_one.refresh_from_db()

        # ۱. منطق اعتبار و کیف پول باید دقیقا مثل مزایده در حال اجرا باشد
        self.assertEqual(self.user_one.get_reserved_auction_credit(), Decimal('20000000'))
        self.assertEqual(self.user_one.current_credit, Decimal('80000000'))

        # ۲. در پروفایل باید در سبد خرید باشد، نه در خریدهای مزایده
        self.client.force_login(self.user_one)
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'سبد خرید مزایده')
        self.assertContains(response, 'تمدید شده')
        self.assertNotContains(response, 'این محصول به بخش خریدهای مزایده شما منتقل شده است.')
        self.assertEqual(len(response.context['current_auction_cart_items']), 1)
        self.assertEqual(len(response.context['auction_purchases']), 0)

        # ۳. ثبت درخواست افزایش اعتبار در زمان تمدید فعال باشد
        credit_resp = self.client.post(
            reverse('auction:submit_credit_increase_ajax'),
            {},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(credit_resp.status_code, 200)
        credit_data = credit_resp.json()
        self.assertTrue(credit_data['success'])
        latest_req = CreditIncreaseRequest.objects.filter(user=self.user_one).first()
        self.assertIsNotNone(latest_req)
        self.assertEqual(latest_req.current_credit, Decimal('80000000'))

    def test_profile_separates_store_purchases_from_auction_purchases(self):
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
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
        self.product.place_bid(self.user_one, '20000000')
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
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1003',
            title='محصول لات 2',
            lot=2,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1004',
            title='محصول بدون لات',
            lot=None,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
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
        )
        AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-1006',
            title='محصول بدون لات',
            lot=None,
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('100'),
        )

        product_titles = list(
            AuctionProduct.objects.filter(auction=self.auction).values_list('title', flat=True)
        )

        self.assertIn(
            product_titles,
            [
                ['محصول لات 3', 'محصول بدون لات', 'تابلو تست'],
                ['محصول بدون لات', 'محصول لات 3', 'تابلو تست'],
            ],
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
        self.user_one.preferred_contact_methods = ['email']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])
        self.user_two.email = 'other@example.com'
        self.user_two.preferred_contact_methods = ['email']
        self.user_two.save(update_fields=['email', 'preferred_contact_methods'])
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
        self.auction.save(update_fields=['end_date'])

        send_auction_ended_email(self.auction.id, expected_end=self.auction.end_date.isoformat())

        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        subjects = [item.subject for item in email_deliveries]
        self.assertIn(f"مزایده «{self.auction.name}» به پایان رسید", subjects)
        self.assertIn("نتیجه مزایده و صورتحساب خرید", subjects)
        winner_messages = [item for item in email_deliveries if item.recipients == ['winner@example.com']]
        self.assertTrue(winner_messages)
        winner_mail = next(
            item for item in winner_messages
            if item.subject == "نتیجه مزایده و صورتحساب خرید"
        )
        self.assertIn('صورتحساب خرید شما صادر شده است', winner_mail.body)
        self.assertIn('جمع مبلغ نهایی پیشنهاد', winner_mail.body)

    def test_send_auction_ended_email_sends_sms_billing_for_sms_only_winner(self):
        self.user_one.email = ''
        self.user_one.preferred_contact_methods = ['sms']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
        self.auction.save(update_fields=['end_date'])

        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            channel=NotificationChannel.SMS,
            status=NotificationStatus.SENT,
            recipients=['09120000001'],
            detail='OK',
        )

        with patch('notifications.providers.EmailProvider.send') as mock_email_send, \
             patch('notifications.providers.SMSProvider.send', return_value=sms_res) as mock_sms_send:
            send_auction_ended_email(self.auction.id, expected_end=self.auction.end_date.isoformat())

        mock_email_send.assert_not_called()
        mock_sms_send.assert_called_once()
        sms_payload = mock_sms_send.call_args.args[0]
        self.assertEqual(sms_payload.event, 'auction.winner.billing')
        self.assertEqual(sms_payload.metadata['sms_pattern'], 'auction_Invoice')
        self.assertEqual(sms_payload.context['AUCTIONNAME'], self.auction.name)
        self.assertEqual(sms_payload.context['NAME'], self.user_one.full_name)
        self.assertEqual(sms_payload.context['FORMAT_AMOUNTTOTAL_AMOUNT'], '20,000,000')
        self.assertEqual(sms_payload.context['NUMBER_OF_PRODUCTS'], '1')
        self.assertEqual(sms_payload.context['FINAL_BID_AMOUNT'], '20,000,000')

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
        self.assertTrue(all('یادآوری شروع مزایده' in item.subject for item in email_deliveries))
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
        self.assertIn('شروع مزایده', email_deliveries[0].subject)

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
        self.assertTrue(all('یادآوری شروع مزایده' in item.subject for item in email_deliveries))

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
        self.user_one.preferred_contact_methods = ['email']
        self.user_one.save(update_fields=['email', 'preferred_contact_methods'])
        self.user_two.email = 'other@example.com'
        self.user_two.preferred_contact_methods = ['email']
        self.user_two.save(update_fields=['email', 'preferred_contact_methods'])
        self.product.place_bid(self.user_one, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
        self.auction.save(update_fields=['end_date'])
        NotificationDelivery.objects.all().delete()

        response = self.client.get(reverse('auction:action'))

        self.assertEqual(response.status_code, 200)
        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        subjects = [item.subject for item in email_deliveries]
        self.assertIn(f"مزایده «{self.auction.name}» به پایان رسید", subjects)
        self.assertIn("نتیجه مزایده و صورتحساب خرید", subjects)

        cache.clear()
        second_response = self.client.get(reverse('auction:action'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            len([item for item in NotificationDelivery.objects.filter(provider='email') if item.subject == f"مزایده «{self.auction.name}» به پایان رسید"]),
            1,
        )
        self.assertEqual(
            len([item for item in NotificationDelivery.objects.filter(provider='email') if item.subject == "نتیجه مزایده و صورتحساب خرید"]),
            1,
        )
        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.end_notice_dispatched_at)
        self.assertIsNotNone(self.auction.winner_billing_dispatched_at)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_dispatch_command_handles_starting_soon_without_5min_restriction(self):
        from django.core.management import call_command
        self.user_one.email = 'first@example.com'
        self.user_one.save(update_fields=['email'])

        # Start date is 10 hours from now (way past old 5-minute window)
        self.auction.start_date = timezone.now() + timedelta(hours=10)
        self.auction.end_date = self.auction.start_date + timedelta(hours=2)
        self.auction.start_reminder_24h_dispatched_at = None
        self.auction.save(update_fields=['start_date', 'end_date', 'start_reminder_24h_dispatched_at'])
        NotificationDelivery.objects.all().delete()

        call_command('dispatch_auction_notifications')

        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.start_reminder_24h_dispatched_at)
        deliveries = NotificationDelivery.objects.filter(event='auction.start.reminder_24h')
        self.assertTrue(deliveries.exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_dispatch_command_handles_started_notice_without_5min_restriction(self):
        from django.core.management import call_command
        self.user_one.email = 'first@example.com'
        self.user_one.save(update_fields=['email'])

        # Start date was 30 minutes ago (way past old 5-minute window)
        self.auction.start_date = timezone.now() - timedelta(minutes=30)
        self.auction.end_date = timezone.now() + timedelta(hours=2)
        self.auction.start_notice_dispatched_at = None
        self.auction.save(update_fields=['start_date', 'end_date', 'start_notice_dispatched_at'])
        NotificationDelivery.objects.all().delete()

        call_command('dispatch_auction_notifications')

        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.start_notice_dispatched_at)
        deliveries = NotificationDelivery.objects.filter(event='auction.start.started')
        self.assertTrue(deliveries.exists())


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

    def test_auction_product_detail_page_is_public_for_guest_users(self):
        response = self.client.get(reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ورود جهت ثبت پیشنهاد')
        self.assertEqual(AuctionVisitHistory.objects.count(), 0)

    def test_auction_product_detail_page_is_public_for_unverified_users(self):
        unverified_user = CustomUser.objects.create_user(
            phone_number='09120000110',
            password='Test@1234',
            full_name='کاربر تاییدنشد‌ه',
        )
        self.client.force_login(unverified_user)

        response = self.client.get(reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bid-submit-form"', html=False)

    def test_finished_auction_product_detail_is_public_without_bid_submission(self):
        winner = CustomUser.objects.create_user(
            phone_number='09120000111',
            password='Test@1234',
            full_name='برنده مزایده',
        )
        winner.is_verified = 1
        winner.credit = Decimal('100000000')
        winner.current_credit = Decimal('100000000')
        winner.save()

        self.product.place_bid(winner, '20000000')
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
        winner.credit = Decimal('100000000')
        winner.current_credit = Decimal('100000000')
        winner.save()

        self.product.place_bid(winner, '20000000')
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
        self.assertIn('return canViewAuctionProductDetails();', html)

    def test_track_visit_endpoint_creates_auction_product_visit_only_on_click(self):
        response = self.client.post(
            reverse('track_public_visit'),
            data=json.dumps({'kind': 'auction_product', 'object_id': self.product.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)

    def test_finished_auction_product_detail_is_public_without_bid_submission(self):
        winner = CustomUser.objects.create_user(
            phone_number='09120000111',
            password='Test@1234',
            full_name='برنده مزایده',
        )
        winner.is_verified = 1
        winner.credit = Decimal('100000000')
        winner.current_credit = Decimal('100000000')
        winner.save()

        self.product.place_bid(winner, '20000000')
        now_ended = timezone.now() - timedelta(seconds=1)
        self.product.extended_end_time = now_ended
        self.product.save(update_fields=['extended_end_time'])
        self.auction.end_date = now_ended
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
        winner.credit = Decimal('100000000')
        winner.current_credit = Decimal('100000000')
        winner.save()

        self.product.place_bid(winner, '20000000')
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
        self.assertIn('return canViewAuctionProductDetails();', html)

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

    def test_product_detail_page_accessible_when_auction_not_started(self):
        ready_auction = Auction.objects.create(
            name='مزایده به زودی',
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
            products_count=1,
        )
        ready_product = AuctionProduct.objects.create(
            auction=ready_auction,
            product_id='A-9999',
            title='اثر پیش‌نمایش',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('500'),
        )
        response = self.client.get(reverse('auction:auction_product_detail', kwargs={'pk': ready_product.pk}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('اثر پیش‌نمایش', html)
        self.assertIn('در انتظار شروع مزایده', html)

    def test_product_detail_back_button_and_lot_navigation(self):
        # Create 3 products with lots 1, 2, 3
        self.product.lot = 1
        self.product.save()

        p2 = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-102',
            lot=2,
            title='اثر لات دوم',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('20000000'),
        )
        p3 = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='A-103',
            lot=3,
            title='اثر لات سوم',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('30000000'),
        )

        auction_back_url = reverse('auction:auction_products', kwargs={'pk': self.auction.pk})
        p1_url = reverse('auction:auction_product_detail', kwargs={'pk': self.product.pk})
        p2_url = reverse('auction:auction_product_detail', kwargs={'pk': p2.pk})
        p3_url = reverse('auction:auction_product_detail', kwargs={'pk': p3.pk})

        # Test Lot 1 (First lot): Next lot is Lot 2, Previous is None (disabled)
        resp1 = self.client.get(p1_url)
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, auction_back_url)
        self.assertContains(resp1, 'بازگشت به مزایده')
        self.assertContains(resp1, p2_url)
        self.assertEqual(resp1.context['previous_lot_product'], None)
        self.assertEqual(resp1.context['next_lot_product']['pk'], p2.pk)

        # Test Lot 2 (Middle lot): Previous is Lot 1, Next is Lot 3
        resp2 = self.client.get(p2_url)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, auction_back_url)
        self.assertContains(resp2, p1_url)
        self.assertContains(resp2, p3_url)
        self.assertEqual(resp2.context['previous_lot_product']['pk'], self.product.pk)
        self.assertEqual(resp2.context['next_lot_product']['pk'], p3.pk)

        # Test Lot 3 (Last lot): Previous is Lot 2, Next is None (disabled)
        resp3 = self.client.get(p3_url)
        self.assertEqual(resp3.status_code, 200)
        self.assertContains(resp3, auction_back_url)
        self.assertContains(resp3, p2_url)
        self.assertEqual(resp3.context['previous_lot_product']['pk'], p2.pk)
        self.assertEqual(resp3.context['next_lot_product'], None)


class AuctionSoftCloseOvertimeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=200, name='هنرمند سافت کلوز')
        self.artwork_type = ArtworkType.objects.create(name='نقاشی سافت کلوز')
        now = timezone.now()
        self.auction = Auction.objects.create(
            name='مزایده سافت کلوز',
            start_date=now - timedelta(hours=2),
            end_date=now + timedelta(hours=2),  # 2 hours remaining (< 6 hours)
            products_count=2,
        )
        self.product_a = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='SC-001',
            lot=1,
            title='اثر آ',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('10000000'),
        )
        self.product_b = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='SC-002',
            lot=2,
            title='اثر ب',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('15000000'),
        )
        self.user_one = CustomUser.objects.create_user(
            phone_number='09190000001',
            password='Test@1234',
            full_name='بیدزن اول',
        )
        self.user_one.is_verified = 1
        self.user_one.credit = Decimal('100000000')
        self.user_one.current_credit = Decimal('100000000')
        self.user_one.save()

        self.user_two = CustomUser.objects.create_user(
            phone_number='09190000002',
            password='Test@1234',
            full_name='بیدزن دوم',
        )
        self.user_two.is_verified = 1
        self.user_two.credit = Decimal('100000000')
        self.user_two.current_credit = Decimal('100000000')
        self.user_two.save()

    def test_soft_close_extension_within_6_hours(self):
        """Bidding within 6 hours before deadline extends product end time by 6 hours."""
        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)

        self.product_a.refresh_from_db()
        expected_extension = bid_time + timedelta(hours=6)
        self.assertIsNotNone(self.product_a.extended_end_time)
        self.assertEqual(self.product_a.extended_end_time, expected_extension)
        self.assertEqual(self.product_a.extension_count, 1)
        self.assertEqual(self.product_a.end_time, expected_extension)
        self.assertTrue(self.product_a.is_extended)
        self.assertTrue(self.product_a.is_in_extension)

    def test_no_extension_outside_6_hours(self):
        """Bidding more than 6 hours before deadline does NOT trigger extension."""
        now = timezone.now()
        auction_long = Auction.objects.create(
            name='مزایده طولانی',
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=10),  # 10 hours left
            products_count=1,
        )
        prod = AuctionProduct.objects.create(
            auction=auction_long,
            product_id='SC-LONG',
            title='اثر مزایده طولانی',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('10000000'),
        )
        prod.place_bid(self.user_one, None)
        prod.refresh_from_db()
        self.assertIsNone(prod.extended_end_time)
        self.assertEqual(prod.extension_count, 0)
        self.assertEqual(prod.end_time, auction_long.end_date)
        self.assertFalse(prod.is_extended)

    def test_independent_extension_per_artwork(self):
        """Extension of Product A does not affect Product B."""
        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)

        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()

        self.assertTrue(self.product_a.is_extended)
        self.assertFalse(self.product_b.is_extended)
        self.assertEqual(self.product_b.end_time, self.auction.end_date)

        # After auction.end_date has passed, product B is finished but product A is still active
        past_end = self.auction.end_date + timedelta(minutes=10)
        with patch('django.utils.timezone.now', return_value=past_end):
            self.assertEqual(self.product_b.status, 'finished')
            self.assertEqual(self.product_a.status, 'ongoing')

    def test_bidding_allowed_on_extended_product_after_auction_end_date(self):
        """Bids can still be placed on extended items after overall auction.end_date."""
        # 1st bid: 1 hour before end_date -> extended by 6 hours from bid 1
        bid_time_1 = self.auction.end_date - timedelta(hours=1)
        with patch('django.utils.timezone.now', return_value=bid_time_1):
            self.product_a.place_bid(self.user_one, None)

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.extension_count, 1)

        # 2nd bid: 30 minutes AFTER auction.end_date -> should succeed and re-extend 6 hours from bid 2
        bid_time_2 = self.auction.end_date + timedelta(minutes=30)
        with patch('django.utils.timezone.now', return_value=bid_time_2):
            self.product_a.place_bid(self.user_two, None)

        self.product_a.refresh_from_db()
        expected_extension_2 = bid_time_2 + timedelta(hours=6)
        self.assertEqual(self.product_a.extension_count, 2)
        self.assertEqual(self.product_a.extended_end_time, expected_extension_2)
        self.assertEqual(self.product_a.current_price, Decimal('20000000'))

    def test_auction_third_state_extended(self):
        """Auction enters 'extended' status when now > end_date and extended items exist."""
        bid_time = self.auction.end_date - timedelta(hours=1)
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)

        self.product_a.refresh_from_db()

        # During regular auction time
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.assertEqual(self.auction.status, 'ongoing')

        # After regular auction end_date, but before product A's extended end time
        overtime_point = self.auction.end_date + timedelta(hours=1)
        with patch('django.utils.timezone.now', return_value=overtime_point):
            self.assertEqual(self.auction.status, 'extended')
            self.assertEqual(self.auction.get_max_end_date(), self.product_a.extended_end_time)
            self.assertEqual(self.auction.get_active_extended_products_count(), 1)

        # After product A's extended end time has also passed
        past_everything = self.product_a.extended_end_time + timedelta(minutes=5)
        with patch('django.utils.timezone.now', return_value=past_everything):
            self.assertEqual(self.auction.status, 'finished')

    def test_products_list_ordering_extended_first(self):
        """Active extended products must float to the top of the products list."""
        from .views import _order_auction_products_by_lot

        # Product B is lot 2, Product A is lot 1. Normally lot 1 is first.
        # Now extend Product B:
        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_b.place_bid(self.user_one, None)

        ordered = list(_order_auction_products_by_lot(self.auction.products.all()))
        self.assertEqual(ordered[0].pk, self.product_b.pk)
        self.assertEqual(ordered[1].pk, self.product_a.pk)

    def test_realtime_payload_includes_extension_data(self):
        """Live payload contains soft close fields."""
        from .realtime import build_bid_live_payload

        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)

        self.product_a.refresh_from_db()
        payload = build_bid_live_payload(self.product_a)
        self.assertTrue(payload['is_extended'])
        self.assertTrue(payload['is_in_extension'])
        self.assertEqual(payload['extension_count'], 1)
        self.assertEqual(payload['status'], 'ongoing')
        self.assertIn('end_time', payload)
        self.assertGreater(payload['seconds_left'], 0)

    def test_invoice_dispatch_delayed_until_all_extensions_finish(self):
        """Winner billing and invoices must be delayed until all extensions finish."""
        from .scheduled_dispatch import _dispatch_ended

        # 1. Extend product_a
        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)
        self.product_a.refresh_from_db()

        # 2. At official end date, product_a is in extension
        at_official_end = self.auction.end_date + timedelta(seconds=2)
        with patch('django.utils.timezone.now', return_value=at_official_end):
            # Attempt to send ended email / billing
            send_auction_ended_email(self.auction.id, expected_end=self.auction.end_date.isoformat())
            self.auction.refresh_from_db()
            self.assertIsNone(self.auction.winner_billing_dispatched_at)
            self.assertIsNone(self.auction.end_notice_dispatched_at)

            # Also verify _dispatch_ended skips it
            dispatched = _dispatch_ended(now=at_official_end, remaining=10)
            self.assertEqual(dispatched, 0)

        # 3. After product_a's extension period has ended
        past_extension = self.product_a.extended_end_time + timedelta(seconds=10)
        with patch('django.utils.timezone.now', return_value=past_extension):
            send_auction_ended_email(self.auction.id)
            self.auction.refresh_from_db()
            self.assertIsNotNone(self.auction.winner_billing_dispatched_at)

    def test_send_auction_extended_notice_sms_dispatches_pattern_810087(self):
        """When auction reaches end_date with active extensions, SMS pattern 810087 is sent to users."""
        from notifications.providers import SMSProvider

        # 1. Extend product_a
        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)
        self.product_a.refresh_from_db()

        at_official_end = self.auction.end_date + timedelta(seconds=2)
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            status=NotificationStatus.SENT,
            channel=NotificationChannel.SMS,
            recipients=['09190000001'],
            detail='OK',
        )

        with patch('django.utils.timezone.now', return_value=at_official_end), \
             patch.object(SMSProvider, 'send', return_value=sms_res) as mock_sms_send:
            send_auction_extended_notice_sms(self.auction.id)

            self.auction.refresh_from_db()
            self.assertIsNotNone(self.auction.extension_notice_dispatched_at)
            self.assertTrue(mock_sms_send.called)

            # Check sent payload
            payload = mock_sms_send.call_args[0][0]
            self.assertIn(payload.context['number_of_works'], ('1', '۱'))
            self.assertEqual(payload.context['auction_name'], self.auction.name)
            self.assertEqual(payload.metadata.get('sms_pattern'), 'auction_extended_notice')

            # Claim check: calling again must be a no-op
            mock_sms_send.reset_mock()
            send_auction_extended_notice_sms(self.auction.id)
            mock_sms_send.assert_not_called()

    def test_dispatch_due_auction_emails_sends_extension_notice_and_delays_billing(self):
        """dispatch_due_auction_emails dispatches extension notice and skips billing for extended auctions."""
        from .scheduled_dispatch import dispatch_due_auction_emails
        from notifications.providers import SMSProvider

        bid_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=bid_time):
            self.product_a.place_bid(self.user_one, None)
        self.product_a.refresh_from_db()

        at_official_end = self.auction.end_date + timedelta(seconds=2)
        sms_res = NotificationSendResult(
            provider=NotificationProviderType.SMS,
            status=NotificationStatus.SENT,
            channel=NotificationChannel.SMS,
            recipients=['09190000001'],
            detail='OK',
        )

        with patch('django.utils.timezone.now', return_value=at_official_end), \
             patch.object(SMSProvider, 'send', return_value=sms_res):
            dispatch_due_auction_emails()

            self.auction.refresh_from_db()
            # Extension notice must be sent
            self.assertIsNotNone(self.auction.extension_notice_dispatched_at)
            # Invoices / billing must be delayed
            self.assertIsNone(self.auction.winner_billing_dispatched_at)


class AuctionInvoiceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.artist = Artist.objects.create(id=300, name='هنرمند تستی')
        self.artwork_type = ArtworkType.objects.create(name='نقاشی تستی')
        now = timezone.now()
        self.auction = Auction.objects.create(
            name='مزایده بهاره تست',
            start_date=now - timedelta(hours=3),
            end_date=now - timedelta(hours=1),
            products_count=2,
        )
        self.product_1 = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='INV-P01',
            lot=10,
            title='اثر اول فاکتور',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('20000000'),
            current_price=Decimal('25000000'),
        )
        self.product_2 = AuctionProduct.objects.create(
            auction=self.auction,
            product_id='INV-P02',
            lot=11,
            title='اثر دوم فاکتور',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('10000000'),
            current_price=Decimal('15000000'),
        )
        self.winner_user = CustomUser.objects.create_user(
            phone_number='09121111111',
            password='TestPassword123',
            full_name='برنده فاکتور',
        )
        self.winner_user.is_verified = 1
        self.winner_user.save()

        self.other_user = CustomUser.objects.create_user(
            phone_number='09122222222',
            password='TestPassword123',
            full_name='کاربر دیگر',
        )
        self.other_user.is_verified = 1
        self.other_user.save()

        self.admin_user = CustomUser.objects.create_superuser(
            phone_number='09123333333',
            password='AdminPassword123',
            full_name='مدیر سیستم',
        )

        Bid.objects.create(
            auction=self.auction,
            product=self.product_1,
            user=self.winner_user,
            user_fullname=self.winner_user.full_name,
            user_mobile=self.winner_user.phone_number,
            bid_amount=Decimal('25000000'),
        )
        Bid.objects.create(
            auction=self.auction,
            product=self.product_2,
            user=self.winner_user,
            user_fullname=self.winner_user.full_name,
            user_mobile=self.winner_user.phone_number,
            bid_amount=Decimal('15000000'),
        )

        self.product_1.winner = self.winner_user
        self.product_1.save()
        self.product_2.winner = self.winner_user
        self.product_2.save()

    def test_invoice_not_generated_for_ongoing_auction(self):
        now = timezone.now()
        ongoing_auction = Auction.objects.create(
            name='مزایده جاری',
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=1),
            products_count=1,
        )
        AuctionProduct.objects.create(
            auction=ongoing_auction,
            product_id='ONGOING-01',
            title='اثر جاری',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('10000000'),
            winner=self.winner_user,
        )
        from auction.services import create_or_get_invoice_for_winner, generate_invoices_for_auction
        inv = create_or_get_invoice_for_winner(ongoing_auction, self.winner_user)
        self.assertIsNone(inv)
        invs = generate_invoices_for_auction(ongoing_auction)
        self.assertEqual(len(invs), 0)

    def test_invoice_not_generated_when_extended_products_active(self):
        now = timezone.now()
        extended_auction = Auction.objects.create(
            name='مزایده تمدید شده',
            start_date=now - timedelta(hours=3),
            end_date=now - timedelta(minutes=10),
            products_count=1,
        )
        AuctionProduct.objects.create(
            auction=extended_auction,
            product_id='EXT-01',
            title='اثر تمدیدی',
            artist=self.artist,
            artwork_type=self.artwork_type,
            base_price=Decimal('10000000'),
            extended_end_time=now + timedelta(minutes=15),
            winner=self.winner_user,
        )
        from auction.services import create_or_get_invoice_for_winner, generate_invoices_for_auction
        self.assertEqual(extended_auction.status, 'extended')
        inv = create_or_get_invoice_for_winner(extended_auction, self.winner_user)
        self.assertIsNone(inv)
        invs = generate_invoices_for_auction(extended_auction)
        self.assertEqual(len(invs), 0)

    def test_invoice_generation_upon_definitive_finish(self):
        from auction.models import AuctionInvoice
        from auction.tasks import send_auction_ended_email
        self.assertEqual(self.auction.status, 'finished')

        send_auction_ended_email(self.auction.id)

        invoices = AuctionInvoice.objects.filter(auction=self.auction, user=self.winner_user)
        self.assertEqual(invoices.count(), 1)
        invoice = invoices.first()

        self.assertEqual(invoice.total_hammer_price, Decimal('40000000'))
        self.assertEqual(invoice.buyers_premium, Decimal('4000000'))
        self.assertEqual(invoice.total_amount, Decimal('44000000'))
        self.assertTrue(invoice.invoice_number.startswith('INV-'))
        self.assertEqual(invoice.items.count(), 2)

    def test_invoice_pdf_download_permissions(self):
        from auction.services import create_or_get_invoice_for_winner
        invoice = create_or_get_invoice_for_winner(self.auction, self.winner_user)
        self.assertIsNotNone(invoice)

        self.client.force_login(self.winner_user)
        url = reverse('auction:invoice_pdf', args=[invoice.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn(f'attachment; filename="invoice-{invoice.invoice_number}.pdf"', resp['Content-Disposition'])
        self.assertGreater(len(resp.content), 1000)

        self.client.force_login(self.other_user)
        resp2 = self.client.get(url)
        self.assertEqual(resp2.status_code, 403)

        self.client.force_login(self.admin_user)
        resp3 = self.client.get(url)
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3['Content-Type'], 'application/pdf')

    def test_invoice_html_view(self):
        from auction.services import create_or_get_invoice_for_winner
        invoice = create_or_get_invoice_for_winner(self.auction, self.winner_user)
        self.client.force_login(self.winner_user)
        url = reverse('auction:invoice_detail', args=[invoice.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, invoice.invoice_number)
        self.assertContains(resp, 'اثر اول فاکتور')

    def test_profile_context_groups_by_auction(self):
        from accounts.realtime import build_profile_live_context
        ctx = build_profile_live_context(self.winner_user)
        self.assertIn('auction_purchase_groups', ctx)
        groups = ctx['auction_purchase_groups']
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group['auction'].pk, self.auction.pk)
        self.assertEqual(group['items_count'], 2)
        self.assertEqual(group['total_pure_price'], Decimal('40000000'))
        self.assertEqual(group['total_with_tax'], Decimal('44000000'))
        self.assertIsNotNone(group['invoice'])

    def test_admin_api_returns_invoices(self):
        from auction.services import create_or_get_invoice_for_winner
        invoice = create_or_get_invoice_for_winner(self.auction, self.winner_user)
        self.client.force_login(self.admin_user)

        url = reverse('admin_panel:user-auction-invoices-api', args=[self.winner_user.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['results'][0]['invoice_number'], invoice.invoice_number)

        list_url = reverse('admin_panel:products-auction-invoices-list')
        list_resp = self.client.get(list_url)
        self.assertEqual(list_resp.status_code, 200)
        list_data = list_resp.json()
        self.assertEqual(list_data['total'], 1)




