import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, VerificationRequest, CreditIncreaseRequest
from auction.models import Auction, AuctionProduct, AuctionVisitHistory, AuctionCartItem, Bid
from core.models import ActivityLog
from store.models import Artist, Artwork, ArtworkType, SiteVisitLog, VisitHistory, PurchaseHistory, TelegramPurchaseRequest


class AdminRequestManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin_user = CustomUser.objects.create_user(
            phone_number="09120000001",
            password="Admin@1234",
            full_name="ادمین تست",
            is_staff=True,
        )
        self.normal_user = CustomUser.objects.create_user(
            phone_number="09120000002",
            password="User@1234",
            full_name="کاربر تست",
        )
        self.other_user = CustomUser.objects.create_user(
            phone_number="09120000003",
            password="User@1234",
            full_name="کاربر دیگر",
            email="another@example.com",
            telegram_id="another_telegram",
        )
        self.super_user = CustomUser.objects.create_user(
            phone_number="09120000004",
            password="Super@1234",
            full_name="سوپریوزر تست",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin_user)

    def test_non_superuser_staff_cannot_access_superuser_only_product_endpoints(self):
        page_response = self.client.get(reverse('admin_panel_pages:products-create'))
        api_response = self.client.get(reverse('admin_panel:products-store-list'))

        self.assertEqual(page_response.status_code, 403)
        self.assertEqual(api_response.status_code, 403)

    def test_non_superuser_staff_cannot_access_superuser_only_history_endpoints(self):
        page_response = self.client.get(reverse('admin_panel_pages:login-history'))
        api_response = self.client.get(reverse('admin_panel:users-login-history-api'))

        self.assertEqual(page_response.status_code, 403)
        self.assertEqual(api_response.status_code, 403)

    def test_superuser_can_access_superuser_only_endpoints(self):
        self.client.force_login(self.super_user)

        page_response = self.client.get(reverse('admin_panel_pages:products-create'))
        api_response = self.client.get(reverse('admin_panel:users-login-history-api'))

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(api_response.status_code, 200)

    def test_verification_request_can_be_approved_from_admin_panel(self):
        request_obj = VerificationRequest.objects.create(
            user=self.normal_user,
            full_name="کاربر تست",
            phone_number="09120000002",
        )

        url = reverse('admin_panel:requests-detail', args=['verification', request_obj.pk])
        response = self.client.post(
            url,
            data=json.dumps({'action': 'approve', 'amount': 1200}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.normal_user.refresh_from_db()

        self.assertEqual(request_obj.status, VerificationRequest.RequestStatus.APPROVED)
        self.assertEqual(self.normal_user.is_verified, 1)
        self.assertEqual(self.normal_user.credit, 1200)
        self.assertEqual(self.normal_user.current_credit, 1200)

    def test_credit_request_list_returns_pending_status(self):
        self.normal_user.username = 'credit-user'
        self.normal_user.email = 'credit@example.com'
        self.normal_user.is_verified = 1
        self.normal_user.credit = 300
        self.normal_user.current_credit = 75
        self.normal_user.save(refresh_current_credit=False)
        request_obj = CreditIncreaseRequest.objects.create(
            user=self.normal_user,
            current_credit=200,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )

        response = self.client.get(reverse('admin_panel:requests-list'), {'type': 'credit'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['requests'][0]['id'], request_obj.pk)
        self.assertEqual(payload['requests'][0]['status'], 'pending')
        self.assertEqual(payload['requests'][0]['user'], 'کاربر تست')
        self.assertEqual(payload['requests'][0]['current_credit'], '$75.00')
        self.assertEqual(payload['requests'][0]['requested_credit'], '$200.00')
        self.assertEqual(payload['requests'][0]['total_credit'], '$300.00')
        self.assertIsNotNone(payload['requests'][0]['created_at'])
        self.assertEqual(payload['page_size'], 100)

    def test_request_list_supports_user_and_status_sorting(self):
        alpha_user = CustomUser.objects.create_user(
            phone_number="09125550010",
            password="User@1234",
            full_name="Alpha User",
            is_verified=1,
            credit=100,
            current_credit=50,
        )
        alpha_user.save(refresh_current_credit=False)
        beta_user = CustomUser.objects.create_user(
            phone_number="09125550011",
            password="User@1234",
            full_name="Beta User",
            is_verified=1,
            credit=100,
            current_credit=70,
        )
        beta_user.save(refresh_current_credit=False)

        alpha_request = CreditIncreaseRequest.objects.create(
            user=alpha_user,
            current_credit=150,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )
        beta_request = CreditIncreaseRequest.objects.create(
            user=beta_user,
            current_credit=170,
            status=CreditIncreaseRequest.RequestStatus.REJECTED,
        )

        user_sorted_response = self.client.get(
            reverse('admin_panel:requests-list'),
            {'type': 'credit', 'sort': 'user'},
        )
        user_sorted_ids = [item['id'] for item in user_sorted_response.json()['requests']]

        status_sorted_response = self.client.get(
            reverse('admin_panel:requests-list'),
            {'type': 'credit', 'sort': '-status'},
        )
        status_sorted_ids = [item['id'] for item in status_sorted_response.json()['requests']]

        self.assertLess(user_sorted_ids.index(alpha_request.pk), user_sorted_ids.index(beta_request.pk))
        self.assertLess(status_sorted_ids.index(beta_request.pk), status_sorted_ids.index(alpha_request.pk))

    def test_request_detail_endpoints_include_consistent_user_fields(self):
        purchase_user = CustomUser.objects.create_user(
            phone_number="09125550001",
            password="User@1234",
            username='purchase-user',
            first_name='علی',
            last_name='محمدی',
            full_name='علی محمدی',
            email='purchase@example.com',
            telegram_id='purchase_telegram',
            preferred_contact_methods=['telegram', 'email', 'whatsapp'],
            is_verified=1,
            credit=300,
            current_credit=180,
        )
        purchase_user.save(refresh_current_credit=False)

        verification_user = CustomUser.objects.create_user(
            phone_number="09125550002",
            password="User@1234",
            username='verify-user',
            first_name='سارا',
            last_name='احمدی',
            full_name='سارا احمدی',
            email='verify@example.com',
        )

        credit_user = CustomUser.objects.create_user(
            phone_number="09125550003",
            password="User@1234",
            username='credit-user',
            first_name='رضا',
            last_name='کریمی',
            full_name='رضا کریمی',
            email='credit@example.com',
            is_verified=1,
            credit=500,
            current_credit=275,
        )
        credit_user.save(refresh_current_credit=False)

        artist = Artist.objects.create(id=301, name="هنرمند درخواست")
        artwork_type = ArtworkType.objects.create(name="نقاشی درخواست")
        artwork = Artwork.objects.create(
            title="اثر تستی درخواست",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح تستی",
            price=1200,
        )
        purchase_request = TelegramPurchaseRequest.objects.create(
            user=purchase_user,
            artwork=artwork,
            telegram_chat_id='chat_101',
            status='pending',
        )
        verification_request = VerificationRequest.objects.create(
            user=verification_user,
            full_name='سارا احمدی',
            phone_number=verification_user.phone_number,
            status=VerificationRequest.RequestStatus.PENDING,
        )
        credit_request = CreditIncreaseRequest.objects.create(
            user=credit_user,
            current_credit=220,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )

        purchase_user.refresh_from_db()
        verification_user.refresh_from_db()
        credit_user.refresh_from_db()

        purchase_payload = self.client.get(
            reverse('admin_panel:requests-detail', args=['purchase', purchase_request.pk])
        ).json()
        verification_payload = self.client.get(
            reverse('admin_panel:requests-detail', args=['verification', verification_request.pk])
        ).json()
        credit_payload = self.client.get(
            reverse('admin_panel:requests-detail', args=['credit', credit_request.pk])
        ).json()

        self.assertEqual(purchase_payload['username'], 'purchase-user')
        self.assertEqual(purchase_payload['full_name'], 'علی محمدی')
        self.assertEqual(purchase_payload['first_name'], 'علی')
        self.assertEqual(purchase_payload['last_name'], 'محمدی')
        self.assertEqual(purchase_payload['phone_number'], purchase_user.phone_number)
        self.assertEqual(purchase_payload['email'], 'purchase@example.com')
        self.assertEqual(purchase_payload['is_verified'], True)
        self.assertEqual(purchase_payload['current_credit'], str(purchase_user.current_credit))

        self.assertEqual(purchase_payload['product'], 'اثر تستی درخواست')
        self.assertEqual(purchase_payload['price'], '1200')
        self.assertIn(purchase_user.phone_number, purchase_payload['contact_ways'])
        self.assertIn('تلگرام', purchase_payload['contact_ways'])
        self.assertIn('ایمیل', purchase_payload['contact_ways'])
        self.assertEqual(purchase_payload['telegram_chat_id'], 'chat_101')
        self.assertIsNotNone(purchase_payload['updated_at'])

        self.assertEqual(verification_payload['username'], 'verify-user')
        self.assertEqual(verification_payload['full_name'], 'سارا احمدی')
        self.assertEqual(verification_payload['first_name'], 'سارا')
        self.assertEqual(verification_payload['last_name'], 'احمدی')
        self.assertEqual(verification_payload['phone_number'], verification_user.phone_number)
        self.assertEqual(verification_payload['email'], 'verify@example.com')
        self.assertEqual(verification_payload['is_verified'], False)
        self.assertEqual(verification_payload['current_credit'], str(verification_user.current_credit))
        self.assertEqual(verification_payload['granted_credit'], '0')

        self.assertEqual(credit_payload['username'], 'credit-user')
        self.assertEqual(credit_payload['full_name'], 'رضا کریمی')
        self.assertEqual(credit_payload['first_name'], 'رضا')
        self.assertEqual(credit_payload['last_name'], 'کریمی')
        self.assertEqual(credit_payload['phone_number'], credit_user.phone_number)
        self.assertEqual(credit_payload['email'], 'credit@example.com')
        self.assertEqual(credit_payload['is_verified'], True)
        self.assertEqual(credit_payload['total_credit'], str(credit_user.credit))
        self.assertEqual(credit_payload['current_credit'], str(credit_user.current_credit))
        self.assertEqual(credit_payload['requested_credit'], '220')

    def test_requests_page_sidebar_links_target_request_types(self):
        response = self.client.get(reverse('admin_panel_pages:requests'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f"{reverse('admin_panel_pages:requests')}?type=purchase", html)
        self.assertIn(f"{reverse('admin_panel_pages:requests')}?type=verification", html)
        self.assertIn(f"{reverse('admin_panel_pages:requests')}?type=credit", html)

    def test_bulk_request_actions_are_disabled(self):
        artist = Artist.objects.create(id=302, name="هنرمند عملیات گروهی")
        artwork_type = ArtworkType.objects.create(name="چاپ")
        artwork = Artwork.objects.create(
            title="اثر عملیات گروهی",
            artist=artist,
            artwork_type=artwork_type,
            description="تست",
            price=2200,
        )
        purchase_request = TelegramPurchaseRequest.objects.create(
            user=self.normal_user,
            artwork=artwork,
            status='pending',
        )

        response = self.client.post(
            reverse('admin_panel:requests-bulk'),
            data=json.dumps({'type': 'purchase', 'action': 'approve', 'ids': [purchase_request.pk]}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 405)
        self.assertIn('حذف شده', response.json()['error'])

    def test_user_purchase_requests_summary_api_includes_admin_request_reference(self):
        artist = Artist.objects.create(id=303, name="هنرمند ارجاع درخواست")
        artwork_type = ArtworkType.objects.create(name="طراحی")
        artwork = Artwork.objects.create(
            title="اثر ارجاع درخواست",
            artist=artist,
            artwork_type=artwork_type,
            description="تست لینک",
            price=3300,
        )
        telegram_request = TelegramPurchaseRequest.objects.create(
            user=self.normal_user,
            artwork=artwork,
            telegram_chat_id='chat_303',
            status='pending',
        )

        response = self.client.get(
            reverse('admin_panel:user-purchase-requests-summary-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['results'][0]['source_type'], 'telegram_request')
        self.assertEqual(payload['results'][0]['request_id'], telegram_request.pk)

    def test_credit_request_approval_adds_to_total_credit_and_preserves_reserved_amount(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = 500
        self.normal_user.save()
        request_obj = CreditIncreaseRequest.objects.create(
            user=self.normal_user,
            current_credit=600,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )

        url = reverse('admin_panel:requests-detail', args=['credit', request_obj.pk])
        response = self.client.post(
            url,
            data=json.dumps({'action': 'approve', 'amount': 600}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.normal_user.refresh_from_db()

        self.assertEqual(request_obj.status, CreditIncreaseRequest.RequestStatus.APPROVED)
        self.assertEqual(self.normal_user.credit, 1100)
        self.assertEqual(self.normal_user.current_credit, 1100)

    def test_credit_request_approval_for_unverified_user_returns_validation_error(self):
        request_obj = CreditIncreaseRequest.objects.create(
            user=self.normal_user,
            current_credit=200,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )

        url = reverse('admin_panel:requests-detail', args=['credit', request_obj.pk])
        response = self.client.post(
            url,
            data=json.dumps({'action': 'approve', 'amount': 200}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn('error', payload)
        self.assertIn('وریفای', payload['error'])

    def test_admin_can_update_extended_user_profile_from_detail_endpoint(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = 100
        self.normal_user.current_credit = 100
        self.normal_user.save(refresh_current_credit=False)

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': 'updated_user',
                'full_name': 'علی رضایی',
                'phone_number': '09125554444',
                'email': 'updated@example.com',
                'telegram_id': 'updated_telegram',
                'address_country': 'ایران',
                'address_city': 'تهران',
                'address_street': 'خیابان تست',
                'description': 'توضیحات تستی',
                'is_active': 'on',
                'is_staff': 'on',
                'is_verified': '1',
                'credit': '750',
                'current_credit': '500',
                'new_password': 'Updated@123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()

        self.assertEqual(self.normal_user.username, '09125554444')
        self.assertEqual(self.normal_user.first_name, 'علی')
        self.assertEqual(self.normal_user.last_name, 'رضایی')
        self.assertEqual(self.normal_user.full_name, 'علی رضایی')
        self.assertEqual(self.normal_user.phone_number, '09125554444')
        self.assertEqual(self.normal_user.email, 'updated@example.com')
        self.assertEqual(self.normal_user.telegram_id, 'updated_telegram')
        self.assertEqual(self.normal_user.address_country, 'ایران')
        self.assertEqual(self.normal_user.address_city, 'تهران')
        self.assertEqual(self.normal_user.address_street, 'خیابان تست')
        self.assertEqual(self.normal_user.description, 'توضیحات تستی')
        self.assertTrue(self.normal_user.is_active)
        self.assertTrue(self.normal_user.is_staff)
        self.assertEqual(self.normal_user.is_verified, 1)
        self.assertEqual(self.normal_user.credit, 750)
        self.assertEqual(self.normal_user.current_credit, 750)
        self.assertTrue(self.normal_user.check_password('Updated@123'))

    def test_admin_user_edit_syncs_latest_verification_request_with_verified_state(self):
        verification_request = VerificationRequest.objects.create(
            user=self.normal_user,
            full_name=self.normal_user.full_name,
            phone_number=self.normal_user.phone_number,
            status=VerificationRequest.RequestStatus.PENDING,
        )

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': 'verified_user',
                'full_name': 'کاربر تایید شده',
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '1',
                'credit': '450',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        verification_request.refresh_from_db()

        self.assertEqual(self.normal_user.is_verified, 1)
        self.assertEqual(self.normal_user.credit, 450)
        self.assertEqual(verification_request.status, VerificationRequest.RequestStatus.APPROVED)
        self.assertEqual(verification_request.is_verified, 1)
        self.assertEqual(verification_request.granted_credit, 450)
        self.assertEqual(verification_request.full_name, 'کاربر تایید شده')

    def test_admin_detail_endpoint_recalculates_current_credit_from_active_auction_reserve(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.save()

        artist = Artist.objects.create(id=11, name="هنرمند فرم ادمین")
        artwork_type = ArtworkType.objects.create(name="خوشنویسی")
        auction = Auction.objects.create(
            name="مزایده فرم ادمین",
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        product = AuctionProduct.objects.create(
            auction=auction,
            product_id='ADMIN-1001',
            title='محصول تست ادمین',
            artist=artist,
            artwork_type=artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        product.place_bid(self.normal_user, '200')

        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.current_credit, Decimal('300'))

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '1',
                'credit': '750',
                'current_credit': '999',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()

        self.assertEqual(self.normal_user.credit, Decimal('750'))
        self.assertEqual(self.normal_user.current_credit, Decimal('550'))

    def test_admin_can_reduce_credit_until_current_credit_reaches_zero_when_credit_is_reserved(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.save()

        artist = Artist.objects.create(id=14, name="هنرمند کاهش تا صفر")
        artwork_type = ArtworkType.objects.create(name="مجسمه")
        auction = Auction.objects.create(
            name="مزایده کاهش تا صفر",
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        product = AuctionProduct.objects.create(
            auction=auction,
            product_id='ADMIN-2501',
            title='محصول کاهش تا صفر',
            artist=artist,
            artwork_type=artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        product.place_bid(self.normal_user, '200')

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '1',
                'credit': '200',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.credit, Decimal('200'))
        self.assertEqual(self.normal_user.current_credit, Decimal('0'))

    def test_admin_can_reduce_credit_when_no_auction_credit_is_reserved(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.current_credit = Decimal('500')
        self.normal_user.save(refresh_current_credit=False)

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '1',
                'credit': '300',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.credit, Decimal('300'))
        self.assertEqual(self.normal_user.current_credit, Decimal('300'))

    def test_admin_can_remove_auction_access_when_no_credit_is_reserved(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.current_credit = Decimal('500')
        self.normal_user.save(refresh_current_credit=False)

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '0',
                'credit': '500',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.is_verified, 0)
        self.assertEqual(self.normal_user.credit, Decimal('0'))
        self.assertEqual(self.normal_user.current_credit, Decimal('0'))

    def test_admin_cannot_reduce_credit_below_reserved_amount_or_remove_auction_access_when_credit_is_reserved(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.save()

        artist = Artist.objects.create(id=12, name="هنرمند رزرو ادمین")
        artwork_type = ArtworkType.objects.create(name="نقاشی")
        auction = Auction.objects.create(
            name="مزایده جلوگیری از کاهش",
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        product = AuctionProduct.objects.create(
            auction=auction,
            product_id='ADMIN-2001',
            title='محصول رزروشده',
            artist=artist,
            artwork_type=artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        product.place_bid(self.normal_user, '200')

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '0',
                'credit': '150',
            },
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn('credit', payload['errors'])
        self.assertIn('is_verified', payload['errors'])

    def test_admin_can_reduce_credit_after_reserved_auction_has_finished(self):
        self.normal_user.is_verified = 1
        self.normal_user.credit = Decimal('500')
        self.normal_user.save()

        artist = Artist.objects.create(id=13, name="هنرمند مزایده تمام شده")
        artwork_type = ArtworkType.objects.create(name="طراحی")
        auction = Auction.objects.create(
            name="مزایده پایان یافته",
            start_date=timezone.now() - timedelta(hours=2),
            end_date=timezone.now() + timedelta(hours=1),
            products_count=1,
        )
        product = AuctionProduct.objects.create(
            auction=auction,
            product_id='ADMIN-3001',
            title='محصول پایان یافته',
            artist=artist,
            artwork_type=artwork_type,
            base_price=Decimal('100'),
            bid_value=Decimal('10'),
        )
        product.place_bid(self.normal_user, '200')
        auction.end_date = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=['end_date'])

        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': self.normal_user.username,
                'full_name': self.normal_user.full_name,
                'phone_number': self.normal_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_active': 'on',
                'is_verified': '1',
                'credit': '300',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.credit, Decimal('300'))
        self.assertEqual(self.normal_user.current_credit, Decimal('300'))

    def test_admin_detail_endpoint_rejects_duplicate_phone_number(self):
        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': 'duplicate_test',
                'full_name': 'کاربر تستی',
                'phone_number': self.other_user.phone_number,
                'email': '',
                'telegram_id': '',
                'is_verified': '0',
                'credit': '0',
                'current_credit': '0',
            },
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn('phone_number', payload['errors'])

    def test_admin_detail_endpoint_zeroes_credit_for_unverified_user(self):
        url = reverse('admin_panel:users-detail', args=[self.normal_user.pk])
        response = self.client.post(
            url,
            {
                'username': 'credit_error_test',
                'full_name': 'کاربر تستی',
                'phone_number': '09125550000',
                'email': '',
                'telegram_id': '',
                'is_verified': '0',
                'credit': '150',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.is_verified, 0)
        self.assertEqual(self.normal_user.credit, Decimal('0'))
        self.assertEqual(self.normal_user.current_credit, Decimal('0'))

    def test_dashboard_orders_returns_request_detail_links(self):
        artist = Artist.objects.create(id=21, name="هنرمند داشبورد")
        artwork_type = ArtworkType.objects.create(name="نقاشی داشبورد")
        artwork = Artwork.objects.create(
            title="اثر داشبورد",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح اثر",
            price=1000,
        )
        purchase_request = TelegramPurchaseRequest.objects.create(
            user=self.normal_user,
            artwork=artwork,
            status='pending',
        )
        verification_request = VerificationRequest.objects.create(
            user=self.normal_user,
            full_name='کاربر تست',
            phone_number='09120000002',
            status=VerificationRequest.RequestStatus.PENDING,
        )
        credit_request = CreditIncreaseRequest.objects.create(
            user=self.normal_user,
            current_credit=200,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        )

        response = self.client.get(reverse('admin_panel:dashboard-orders'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()['requests']
        href_map = {item['href'] for item in payload}

        self.assertIn(reverse('admin_panel:requests-detail', args=['purchase', purchase_request.pk]), href_map)
        self.assertIn(reverse('admin_panel:requests-detail', args=['verification', verification_request.pk]), href_map)
        self.assertIn(reverse('admin_panel:requests-detail', args=['credit', credit_request.pk]), href_map)

    def test_users_list_includes_auction_request_status(self):
        approved_user = self.normal_user
        approved_user.is_verified = 1
        approved_user.save(refresh_current_credit=False)
        VerificationRequest.objects.create(
            user=approved_user,
            full_name=approved_user.full_name,
            phone_number=approved_user.phone_number,
            status=VerificationRequest.RequestStatus.APPROVED,
            is_verified=1,
        )

        pending_user = self.other_user
        VerificationRequest.objects.create(
            user=pending_user,
            full_name=pending_user.full_name,
            phone_number=pending_user.phone_number,
            status=VerificationRequest.RequestStatus.PENDING,
            is_verified=0,
        )

        no_request_user = CustomUser.objects.create_user(
            phone_number="09120000004",
            password="User@1234",
            full_name="بدون درخواست",
        )

        response = self.client.get(reverse('admin_panel:users-list'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()['users']
        status_map = {str(item['id']): item['auction_request_status'] for item in payload}

        self.assertEqual(status_map[str(approved_user.pk)], 'approved')
        self.assertEqual(status_map[str(pending_user.pk)], 'pending')
        self.assertEqual(status_map[str(no_request_user.pk)], '')

    def test_users_list_does_not_mark_user_approved_only_because_of_historical_request(self):
        historical_user = self.normal_user
        VerificationRequest.objects.create(
            user=historical_user,
            full_name=historical_user.full_name,
            phone_number=historical_user.phone_number,
            status=VerificationRequest.RequestStatus.APPROVED,
            is_verified=1,
        )
        historical_user.refresh_from_db()
        historical_user.is_verified = 0
        historical_user.credit = 0
        historical_user.current_credit = 0
        historical_user.save(refresh_current_credit=False)

        response = self.client.get(reverse('admin_panel:users-list'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()['users']
        status_map = {str(item['id']): item['auction_request_status'] for item in payload}

        self.assertEqual(status_map[str(historical_user.pk)], '')

    def test_users_list_returns_real_visit_counters_and_supports_sorting(self):
        artist = Artist.objects.create(id=1, name="هنرمند تست")
        artwork_type = ArtworkType.objects.create(name="نقاشی")
        store_artwork = Artwork.objects.create(
            title="اثر فروشگاه",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح",
            price=1000,
        )
        auction = Auction.objects.create(
            name="مزایده تست",
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A1001",
            title="محصول مزایده",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح مزایده",
            base_price=1000,
            bid_value=100,
        )

        ActivityLog.objects.create(user=self.normal_user, action="Login", details="ورود تست")
        VisitHistory.objects.create(user=self.normal_user, product=store_artwork)
        VisitHistory.objects.create(user=self.normal_user, product=store_artwork)
        AuctionVisitHistory.objects.create(user=self.normal_user, auction=auction)
        AuctionVisitHistory.objects.create(user=self.normal_user, auction=auction, product=auction_product)

        response = self.client.get(
            reverse('admin_panel:users-list'),
            {'sort': '-store_visits_count'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()['users']
        user_payload = next(item for item in payload if str(item['id']) == str(self.normal_user.pk))

        self.assertEqual(user_payload['store_visits_count'], 2)
        self.assertEqual(user_payload['auction_visits_count'], 1)
        self.assertEqual(user_payload['auction_product_visits_count'], 1)
        self.assertIsNotNone(user_payload['last_activity'])

    def test_user_history_api_returns_site_visit_page_count(self):
        for index in range(21):
            SiteVisitLog.objects.create(
                user=self.normal_user,
                session_key=f"session-{index}",
                ip_address="127.0.0.1",
            )

        response = self.client.get(
            reverse('admin_panel:users-history-api', args=[self.normal_user.pk]),
            {'visit_page': 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['visit_total_count'], 21)
        self.assertEqual(payload['visit_page_count'], 2)
        self.assertEqual(len(payload['site_visit_history']), 20)

    def test_user_product_visits_api_groups_visits_by_product(self):
        artist = Artist.objects.create(id=2, name="هنرمند دوم")
        artwork_type = ArtworkType.objects.create(name="مجسمه")
        first_artwork = Artwork.objects.create(
            title="اثر اول",
            artist=artist,
            artwork_type=artwork_type,
            description="اول",
            price=1500,
        )
        second_artwork = Artwork.objects.create(
            title="اثر دوم",
            artist=artist,
            artwork_type=artwork_type,
            description="دوم",
            price=2500,
        )

        VisitHistory.objects.create(user=self.normal_user, product=first_artwork)
        VisitHistory.objects.create(user=self.normal_user, product=first_artwork)
        VisitHistory.objects.create(user=self.normal_user, product=second_artwork)

        response = self.client.get(
            reverse('admin_panel:user-product-visits-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['total_visit_count'], 3)
        self.assertEqual(payload['type'], 'store_products')
        self.assertEqual(payload['summary']['store_products']['total_visits'], 3)
        first_item = payload['results'][0]
        second_item = payload['results'][1]
        visit_counts = sorted([first_item['visit_count'], second_item['visit_count']], reverse=True)
        self.assertEqual(visit_counts, [2, 1])
        self.assertTrue(all('last_visit' in item for item in payload['results']))

    def test_user_product_visits_api_supports_auction_products_and_auctions(self):
        artist = Artist.objects.create(id=5, name="هنرمند پنجم")
        artwork_type = ArtworkType.objects.create(name="طراحی")
        auction = Auction.objects.create(
            name="مزایده بازدید",
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A1003",
            title="محصول بازدیدی",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح",
            base_price=4000,
            bid_value=200,
        )

        AuctionVisitHistory.objects.create(user=self.normal_user, auction=auction, product=auction_product)
        AuctionVisitHistory.objects.create(user=self.normal_user, auction=auction, product=auction_product)
        AuctionVisitHistory.objects.create(user=self.normal_user, auction=auction)

        auction_product_response = self.client.get(
            reverse('admin_panel:user-product-visits-api', args=[self.normal_user.pk]),
            {'type': 'auction_products'},
        )
        self.assertEqual(auction_product_response.status_code, 200)
        auction_product_payload = auction_product_response.json()
        self.assertEqual(auction_product_payload['type'], 'auction_products')
        self.assertEqual(auction_product_payload['total'], 1)
        self.assertEqual(auction_product_payload['total_visit_count'], 2)
        self.assertEqual(auction_product_payload['results'][0]['auction_name'], 'مزایده بازدید')

        auction_response = self.client.get(
            reverse('admin_panel:user-product-visits-api', args=[self.normal_user.pk]),
            {'type': 'auctions'},
        )
        self.assertEqual(auction_response.status_code, 200)
        auction_payload = auction_response.json()
        self.assertEqual(auction_payload['type'], 'auctions')
        self.assertEqual(auction_payload['total'], 1)
        self.assertEqual(auction_payload['total_visit_count'], 1)
        self.assertEqual(auction_payload['results'][0]['auction_name'], 'مزایده بازدید')
        self.assertEqual(auction_payload['summary']['auction_products']['total_visits'], 2)
        self.assertEqual(auction_payload['summary']['auctions']['total_visits'], 1)

    def test_user_history_page_points_fetch_calls_to_api_urls(self):
        response = self.client.get(
            reverse('admin_panel_pages:user-history', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn(f'/api/admin/users/{self.normal_user.pk}/', html)
        self.assertIn(f'/api/admin/users/{self.normal_user.pk}/history-api/', html)
        self.assertIn("بازدید محصولات فروشگاه", html)
        self.assertIn("بازدید محصولات مزایده", html)
        self.assertIn("بازدید مزایده", html)
        self.assertIn(f'/api/admin/users/{self.normal_user.pk}/cart-bids-summary/', html)
        self.assertIn(f'/api/admin/users/{self.normal_user.pk}/purchase-requests-summary/', html)

    def test_user_cart_bids_summary_api_groups_bids_under_cart_products(self):
        artist = Artist.objects.create(id=3, name="هنرمند سوم")
        artwork_type = ArtworkType.objects.create(name="چاپ")
        auction = Auction.objects.create(
            name="مزایده ویژه",
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A1002",
            title="محصول رزروی",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح",
            base_price=5000,
            bid_value=250,
        )
        first_bid = Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=5500,
            user=self.normal_user,
            user_fullname=self.normal_user.full_name,
            user_mobile=self.normal_user.phone_number,
        )
        Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=6000,
            user=self.normal_user,
            user_fullname=self.normal_user.full_name,
            user_mobile=self.normal_user.phone_number,
        )
        AuctionCartItem.objects.create(
            user=self.normal_user,
            auction=auction,
            product=auction_product,
            bid=first_bid,
            reserved_amount=7000,
            is_active=True,
        )

        response = self.client.get(
            reverse('admin_panel:user-cart-bids-summary-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['active_total'], 1)
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['results'][0]['product_title'], 'محصول رزروی')
        self.assertEqual(payload['results'][0]['bid_count'], 2)
        self.assertEqual(len(payload['results'][0]['bids']), 2)
        self.assertIn('سبد خرید مزایده', payload['html'])

    def test_user_cart_bids_summary_api_ignores_finished_auction_in_active_totals(self):
        artist = Artist.objects.create(id=5, name="هنرمند پنجم")
        artwork_type = ArtworkType.objects.create(name="چاپ دیجیتال")
        auction = Auction.objects.create(
            name="مزایده تمام شده",
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(minutes=1),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A1003",
            title="محصول مزایده تمام شده",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح",
            base_price=5000,
            bid_value=250,
        )
        first_bid = Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=5500,
            user=self.normal_user,
            user_fullname=self.normal_user.full_name,
            user_mobile=self.normal_user.phone_number,
        )
        AuctionCartItem.objects.create(
            user=self.normal_user,
            auction=auction,
            product=auction_product,
            bid=first_bid,
            reserved_amount=7000,
            is_active=True,
        )

        response = self.client.get(
            reverse('admin_panel:user-cart-bids-summary-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['active_total'], 0)
        self.assertEqual(payload['reserved_total_amount'], '0')
        self.assertEqual(payload['past_total'], 1)
        self.assertIn('مزایده‌های گذشته', payload['html'])

    def test_user_cart_bids_summary_api_renders_rank_badges_from_profile_partial(self):
        artist = Artist.objects.create(id=8, name="هنرمند رتبه")
        artwork_type = ArtworkType.objects.create(name="اکریلیک")
        auction = Auction.objects.create(
            name="مزایده رتبه",
            start_date=timezone.now() - timedelta(hours=2),
            end_date=timezone.now() + timedelta(hours=2),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A2001",
            title="محصول رتبه‌ای",
            artist=artist,
            artwork_type=artwork_type,
            description="توضیح",
            base_price=5000,
            bid_value=250,
        )
        Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=6200,
            user=self.other_user,
            user_fullname=self.other_user.full_name,
            user_mobile=self.other_user.phone_number,
        )
        first_bid = Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=6000,
            user=self.normal_user,
            user_fullname=self.normal_user.full_name,
            user_mobile=self.normal_user.phone_number,
        )
        AuctionCartItem.objects.create(
            user=self.normal_user,
            auction=auction,
            product=auction_product,
            bid=first_bid,
            reserved_amount=6000,
            is_active=False,
        )

        response = self.client.get(
            reverse('admin_panel:user-cart-bids-summary-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('رتبه دوم', payload['html'])
        self.assertIn('دیگر بالاترین پیشنهاد نیست', payload['html'])

    def test_user_purchase_requests_summary_api_matches_profile_purchase_sections(self):
        artist = Artist.objects.create(id=4, name="هنرمند چهارم")
        artwork_type = ArtworkType.objects.create(name="عکس")
        store_artwork = Artwork.objects.create(
            title="اثر فروشگاه",
            artist=artist,
            artwork_type=artwork_type,
            description="رزرو",
            price=3500,
            is_sold=Artwork.IsSoldStatus.SOLD,
        )
        auction = Auction.objects.create(
            name="مزایده خرید",
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(minutes=1),
            products_count=1,
        )
        auction_product = AuctionProduct.objects.create(
            auction=auction,
            product_id="A3001",
            title="اثر مزایده",
            artist=artist,
            artwork_type=artwork_type,
            description="خرید",
            price=8500,
            base_price=8000,
            bid_value=250,
        )
        winning_bid = Bid.objects.create(
            auction=auction,
            product=auction_product,
            bid_amount=9000,
            user=self.normal_user,
            user_fullname=self.normal_user.full_name,
            user_mobile=self.normal_user.phone_number,
        )
        AuctionCartItem.objects.create(
            user=self.normal_user,
            auction=auction,
            product=auction_product,
            bid=winning_bid,
            reserved_amount=9000,
            is_active=True,
        )
        auction_product.winner = self.normal_user
        auction_product.current_price = 9000
        auction_product.save(update_fields=['winner', 'current_price'])

        PurchaseHistory.objects.create(
            user=self.normal_user,
            artwork=store_artwork,
        )

        response = self.client.get(
            reverse('admin_panel:user-purchase-requests-summary-api', args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['store_purchases_total'], 1)
        self.assertEqual(payload['auction_purchases_total'], 1)
        self.assertEqual(payload['purchased_total'], 2)
        self.assertIn('خریدهای فروشگاه', payload['html'])
        self.assertIn('خریدهای مزایده', payload['html'])
        self.assertIn('اثر فروشگاه', payload['html'])
        self.assertIn('اثر مزایده', payload['html'])
        self.assertIn('برنده مزایده', payload['html'])
