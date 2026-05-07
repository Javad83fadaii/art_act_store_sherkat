from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from accounts.models import CreditIncreaseRequest, CustomUser, VerificationRequest


class VerificationRequestModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            phone_number="09120000000",
            password="Test@1234",
            full_name="کاربر تست",
        )

    def test_approved_verification_request_marks_user_verified(self):
        request_obj = VerificationRequest.objects.create(
            user=self.user,
            full_name="کاربر تست",
            phone_number="09120000000",
            status=VerificationRequest.RequestStatus.APPROVED,
            granted_credit=500,
        )

        self.user.refresh_from_db()
        request_obj.refresh_from_db()

        self.assertEqual(request_obj.is_verified, 1)
        self.assertEqual(self.user.is_verified, 1)
        self.assertEqual(self.user.credit, 500)
        self.assertEqual(self.user.current_credit, 500)

    def test_rejected_verification_request_clears_user_verification(self):
        VerificationRequest.objects.create(
            user=self.user,
            full_name="کاربر تست",
            phone_number="09120000000",
            status=VerificationRequest.RequestStatus.REJECTED,
            granted_credit=500,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.is_verified, 0)
        self.assertEqual(self.user.credit, 0)
        self.assertEqual(self.user.current_credit, 0)

    @patch("accounts.signals._handle_verification_request_side_effects_async")
    def test_created_verification_request_schedules_async_notifications_after_commit(self, side_effects_mock):
        with self.captureOnCommitCallbacks(execute=True):
            request_obj = VerificationRequest.objects.create(
                user=self.user,
                full_name="کاربر تست",
                phone_number="09120000000",
                status=VerificationRequest.RequestStatus.PENDING,
                is_verified=0,
            )

        self.assertTrue(side_effects_mock.called)
        _, kwargs = side_effects_mock.call_args
        self.assertEqual(kwargs["request_id"], request_obj.pk)
        self.assertEqual(kwargs["user_id"], request_obj.user_id)
        self.assertEqual(kwargs["full_name"], "کاربر تست")
        self.assertEqual(kwargs["phone_number"], "09120000000")

    def test_request_auction_verification_ajax_returns_pending_state(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("request_auction_verification"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request_state"], "pending")
        self.assertTrue(
            VerificationRequest.objects.filter(
                user=self.user,
                status=VerificationRequest.RequestStatus.PENDING,
            ).exists()
        )

    def test_signup_with_auction_opt_in_creates_pending_verification_request(self):
        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر جدید",
                "phone_number": "09123334444",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": [],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
                "participate_in_auction": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        new_user = CustomUser.objects.get(phone_number="09123334444")
        pending_qs = VerificationRequest.objects.filter(
                user=new_user,
                status=VerificationRequest.RequestStatus.PENDING,
            )
        self.assertTrue(pending_qs.exists())
        self.assertEqual(pending_qs.count(), 1)

    def test_profile_edit_with_auction_opt_in_creates_pending_verification_request(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("update_profile"),
            {
                "full_name": "کاربر تست",
                "phone_number": self.user.phone_number,
                "address_street": "",
                "email": "",
                "preferred_contact_methods": [],
                "telegram_id": "",
                "participate_in_auction": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            VerificationRequest.objects.filter(
                user=self.user,
                status=VerificationRequest.RequestStatus.PENDING,
            ).exists()
        )


class CreditIncreaseRequestSignalTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            phone_number="09120000001",
            password="Test@1234",
            full_name="کاربر اعتبار",
        )

    @patch("accounts.signals._handle_credit_request_side_effects_async")
    def test_created_credit_request_schedules_async_notifications_after_commit(self, side_effects_mock):
        with self.captureOnCommitCallbacks(execute=True):
            request_obj = CreditIncreaseRequest.objects.create(
                user=self.user,
                current_credit=250,
                status=CreditIncreaseRequest.RequestStatus.PENDING,
            )

        self.assertTrue(side_effects_mock.called)
        _, kwargs = side_effects_mock.call_args
        self.assertEqual(kwargs["request_id"], request_obj.pk)
        self.assertEqual(kwargs["user_id"], request_obj.user_id)
        self.assertEqual(kwargs["user_label"], "کاربر اعتبار")
        self.assertEqual(kwargs["phone_number"], "09120000001")
