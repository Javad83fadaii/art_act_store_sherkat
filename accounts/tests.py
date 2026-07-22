import json

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from accounts.forms import CustomLoginForm, PublicSignupForm
from accounts.models import CreditIncreaseRequest, CustomUser, EmailVerificationOTP, VerificationRequest
from store.models import SiteVisitLog


class VerificationRequestModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            phone_number="09120000000",
            password="Test@1234",
            full_name="کاربر تست",
        )
        self.user.email = "verified-user@example.com"
        self.user.is_email_verified = True
        self.user.save(update_fields=["email", "is_email_verified"])

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
                "email": "fresh_signup@example.com",
                "preferred_contact_methods": [],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
                "newsletter_catalog_opt_in": "on",
                "participate_in_auction": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        new_user = CustomUser.objects.get(phone_number="09123334444")
        self.assertTrue(new_user.newsletter_catalog_opt_in)
        pending_qs = VerificationRequest.objects.filter(
                user=new_user,
                status=VerificationRequest.RequestStatus.PENDING,
            )
        self.assertTrue(pending_qs.exists())
        self.assertEqual(pending_qs.count(), 1)

    def test_signup_page_renders_newsletter_opt_in_field(self):
        response = self.client.get(reverse("signup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تمایل به دریافت خبرنامه و کاتالوگ")

    def test_signup_duplicate_phone_shows_validation_feedback(self):
        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر تکراری",
                "phone_number": "09120000000",
                "address_street": "خیابان تست",
                "email": "duplicate_phone@example.com",
                "preferred_contact_methods": [],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "این شماره موبایل قبلاً در سیستم ثبت شده است.")

    def test_signup_required_field_errors_are_localized_to_persian(self):
        response = self.client.post(reverse("signup"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وارد کردن این فیلد الزامی است.")
        self.assertNotContains(response, "This field is required.")

    def test_login_required_field_errors_are_localized_to_persian(self):
        response = self.client.post(reverse("login"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وارد کردن این فیلد الزامی است.")
        self.assertNotContains(response, "This field is required.")

    def test_login_merges_guest_site_visit_into_authenticated_session(self):
        self.client.get(reverse("login"))
        guest_session_key = self.client.session.session_key

        guest_log = SiteVisitLog.objects.get(session_key=guest_session_key, is_closed=False)
        self.assertIsNone(guest_log.user)

        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.phone_number,
                "password": "Test@1234",
            },
        )

        self.assertEqual(response.status_code, 302)
        authenticated_session_key = self.client.session.session_key
        self.assertNotEqual(guest_session_key, authenticated_session_key)

        self.client.get(reverse("profile"))

        self.assertEqual(SiteVisitLog.objects.count(), 1)
        merged_log = SiteVisitLog.objects.get()
        self.assertEqual(merged_log.user, self.user)
        self.assertEqual(merged_log.session_key, authenticated_session_key)

    def test_required_fields_use_persian_browser_validation_message(self):
        login_form = CustomLoginForm()
        signup_form = PublicSignupForm()

        for field_name in ("username", "password"):
            self.assertIn("لطفا این فیلد را کامل کنید", login_form.fields[field_name].widget.attrs.get("oninvalid", ""))
            self.assertEqual(
                login_form.fields[field_name].widget.attrs.get("oninput"),
                "this.setCustomValidity('')",
            )

        self.assertIn("لطفا این فیلد را کامل کنید", signup_form.fields["phone_number"].widget.attrs.get("oninvalid", ""))
        for field_name, expected_message in (
            ("password1", "لطفا رمز عبور را کامل کنید"),
            ("password2", "لطفا تکرار رمز عبور را کامل کنید"),
        ):
            self.assertIn(expected_message, signup_form.fields[field_name].widget.attrs.get("oninvalid", ""))
            self.assertEqual(
                signup_form.fields[field_name].widget.attrs.get("oninput"),
                "this.setCustomValidity('')",
            )

    def test_signup_email_name_and_password_have_full_persian_browser_messages(self):
        signup_form = PublicSignupForm()

        self.assertIn(
            "لطفا آدرس ایمیل را کامل کنید",
            signup_form.fields["email"].widget.attrs.get("oninvalid", ""),
        )
        self.assertIn(
            "لطفا یک آدرس ایمیل معتبر وارد کنید",
            signup_form.fields["email"].widget.attrs.get("oninvalid", ""),
        )
        self.assertIn(
            "لطفا نام و نام خانوادگی را کامل کنید",
            signup_form.fields["full_name"].widget.attrs.get("oninvalid", ""),
        )
        self.assertEqual(signup_form.fields["password1"].widget.attrs.get("minlength"), "8")
        self.assertIn("patternMismatch", signup_form.fields["password1"].widget.attrs.get("oninvalid", ""))
        self.assertIn(
            "رمز عبور باید حداقل ۸ کاراکتر باشد.",
            signup_form.fields["password1"].widget.attrs.get("oninvalid", ""),
        )
        self.assertIn(
            "رمز عبور باید حداقل ۸ کاراکتر و شامل حرف بزرگ، حرف کوچک و کاراکتر ویژه باشد.",
            signup_form.fields["password1"].widget.attrs.get("oninvalid", ""),
        )

    def test_profile_edit_with_auction_opt_in_creates_pending_verification_request(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("update_profile"),
            {
                "full_name": "کاربر تست",
                "phone_number": self.user.phone_number,
                "address_street": "",
                "email": self.user.email,
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


class EmailVerificationFlowTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            phone_number="09121110000",
            password="Test@1234",
            full_name="کاربر ایمیل",
        )
        self.other_user = CustomUser.objects.create_user(
            phone_number="09121110001",
            password="Test@1234",
            full_name="کاربر دیگر",
            email="used@example.com",
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_send_email_verification_sends_mail_and_invalidates_previous_codes(self):
        self.client.force_login(self.user)
        previous_otp = EmailVerificationOTP.generate_otp(self.user, "fresh@example.com")

        response = self.client.post(
            reverse("send_email_verification"),
            data=json.dumps({"email": "fresh@example.com", "user_id": str(self.user.pk)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Verification code sent successfully.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["fresh@example.com"])

        previous_otp.refresh_from_db()
        self.assertTrue(previous_otp.is_used)

        latest_otp = EmailVerificationOTP.objects.filter(user=self.user, email="fresh@example.com").first()
        self.assertIsNotNone(latest_otp)
        self.assertFalse(latest_otp.is_used)
        self.assertIn(latest_otp.code, mail.outbox[0].body)

    def test_send_email_verification_rejects_other_users_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("send_email_verification"),
            data=json.dumps({"email": "fresh@example.com", "user_id": str(self.other_user.pk)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"],
            "You can only request email verification for your own account.",
        )

    def test_send_email_verification_rejects_duplicate_email(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("send_email_verification"),
            data=json.dumps({"email": "used@example.com", "user_id": str(self.user.pk)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This email address is already in use.")

    def test_verify_email_code_updates_only_authenticated_user(self):
        self.client.force_login(self.user)
        otp = EmailVerificationOTP.generate_otp(self.user, "verified@example.com")

        response = self.client.post(
            reverse("verify_email_code"),
            data=json.dumps({"email": "verified@example.com", "code": otp.code}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Email verified successfully.")

        otp.refresh_from_db()
        self.assertTrue(otp.is_used)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)
        self.assertEqual(self.user.email, "verified@example.com")
