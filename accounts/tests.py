import json

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import Mock, patch

from accounts.forms import CustomLoginForm, PublicSignupForm
from accounts.models import CreditIncreaseRequest, CustomUser, EmailVerificationOTP, SMSVerificationOTP, VerificationRequest
from notifications.models import NotificationDelivery
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
                "preferred_contact_methods": ["email"],
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

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_signup_sends_welcome_email_and_verification_code(self):
        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر خوش آمد",
                "phone_number": "09123335555",
                "address_street": "خیابان تست",
                "email": "welcome@example.com",
                "preferred_contact_methods": ["email"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 302)
        deliveries = list(NotificationDelivery.objects.order_by('created_at'))
        self.assertEqual(len(deliveries), 2)
        email_deliveries = [item for item in deliveries if item.provider == 'email']
        self.assertEqual(len(email_deliveries), 2)
        self.assertEqual(email_deliveries[0].recipients, ["welcome@example.com"])
        self.assertIn("خوش آمد", email_deliveries[0].subject)
        self.assertEqual(email_deliveries[1].recipients, ["welcome@example.com"])
        self.assertIn("کد تایید ایمیل", email_deliveries[1].subject)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    @patch("accounts.views.send_welcome_email", side_effect=Exception("welcome failed"))
    def test_signup_surfaces_welcome_email_failure_in_alert(self, _welcome_mock):
        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر خطا",
                "phone_number": "09123336666",
                "address_street": "خیابان تست",
                "email": "welcome-failure@example.com",
                "preferred_contact_methods": ["email"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 302)
        email_deliveries = list(
            NotificationDelivery.objects.filter(provider='email').order_by('created_at')
        )
        self.assertEqual(len(email_deliveries), 1)
        self.assertIn("کد تایید ایمیل", email_deliveries[0].subject)
        self.assertEqual(self.client.session["email_verification_alert"]["type"], "error")
        self.assertIn("ایمیل خوش‌آمدگویی", self.client.session["email_verification_alert"]["message"])
        self.assertIn("welcome failed", self.client.session["email_verification_alert"]["message"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
            "signup_welcome": {
                "code": "377204",
                "variables": ("NAME",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_signup_honors_sms_only_preference_for_notifications(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر پیامک",
                "phone_number": "09123337777",
                "address_street": "خیابان تست",
                "email": "sms-only@example.com",
                "preferred_contact_methods": ["sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("sms_verification"))
        deliveries = list(NotificationDelivery.objects.order_by("created_at"))
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(
            [item.provider for item in deliveries],
            ["sms", "sms"],
        )
        self.assertEqual(
            [item.event for item in deliveries],
            ["accounts.signup.welcome_sms", "accounts.signup.verification_code"],
        )
        self.assertEqual(deliveries[0].recipients, ["9123337777"])
        self.assertEqual(deliveries[0].metadata["pattern_name"], "signup_welcome")
        self.assertEqual(deliveries[1].recipients, ["9123337777"])
        self.assertEqual(deliveries[1].metadata["pattern_name"], "verification")
        self.assertEqual(NotificationDelivery.objects.filter(provider="email").count(), 0)
        self.assertEqual(mail.outbox, [])
        user = CustomUser.objects.get(phone_number="09123337777")
        self.assertFalse(user.is_active)
        self.assertTrue(SMSVerificationOTP.objects.filter(user=user, phone_number="09123337777").exists())
        self.assertEqual(post_mock.call_count, 2)
        sent_template_ids = [call.kwargs["json"]["templateId"] for call in post_mock.call_args_list]
        self.assertEqual(sent_template_ids, [377204, 210072])
        self.assertEqual(
            post_mock.call_args_list[0].kwargs["json"]["parameters"],
            [
                {
                    "name": "NAME",
                    "value": "کاربر پیامک",
                },
            ],
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
            "signup_welcome": {
                "code": "377204",
                "variables": ("NAME",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_signup_honors_email_and_sms_preferences_together(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر دوکاناله",
                "phone_number": "09123338888",
                "address_street": "خیابان تست",
                "email": "both@example.com",
                "preferred_contact_methods": ["email", "sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("email_verification"))
        user = CustomUser.objects.get(phone_number="09123338888")
        self.assertFalse(user.is_active)
        deliveries = list(NotificationDelivery.objects.order_by("created_at"))
        self.assertEqual(len(deliveries), 3)
        self.assertEqual(
            [item.provider for item in deliveries],
            ["sms", "email", "email"],
        )
        self.assertEqual(
            [item.event for item in deliveries],
            [
                "accounts.signup.welcome_sms",
                "accounts.signup.welcome",
                "accounts.signup.verification_code",
            ],
        )
        self.assertEqual(len(mail.outbox), 2)
        post_mock.assert_called_once()
        self.assertEqual(post_mock.call_args.kwargs["json"]["templateId"], 377204)
        self.assertEqual(
            post_mock.call_args.kwargs["json"]["parameters"],
            [
                {
                    "name": "NAME",
                    "value": "کاربر دوکاناله",
                },
            ],
        )

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
                "preferred_contact_methods": ["sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "این شماره موبایل قبلاً در سیستم ثبت شده است.")

    def test_signup_requires_at_least_one_contact_method(self):
        form = PublicSignupForm(
            data={
                "full_name": "کاربر تست",
                "phone_number": "09123330000",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": [],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["preferred_contact_methods"],
            ["حداقل یکی از روش‌های ارتباطی را انتخاب کنید."],
        )

    def test_signup_requires_email_when_email_contact_method_is_selected(self):
        form = PublicSignupForm(
            data={
                "full_name": "کاربر تست",
                "phone_number": "09123330001",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": ["email"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["email"],
            ["در صورت انتخاب «ایمیل»، وارد کردن آدرس ایمیل الزامی است."],
        )

    def test_signup_requires_phone_number_when_sms_contact_method_is_selected(self):
        form = PublicSignupForm(
            data={
                "full_name": "کاربر تست",
                "phone_number": "",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": ["sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["phone_number"],
            ["در صورت انتخاب «پیامک»، وارد کردن شماره موبایل الزامی است."],
        )

    def test_signup_requires_both_email_and_phone_when_email_and_sms_are_selected(self):
        form = PublicSignupForm(
            data={
                "full_name": "کاربر تست",
                "phone_number": "",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": ["email", "sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["email"],
            ["در صورت انتخاب «ایمیل»، وارد کردن آدرس ایمیل الزامی است."],
        )
        self.assertEqual(
            form.errors["phone_number"],
            ["در صورت انتخاب «پیامک»، وارد کردن شماره موبایل الزامی است."],
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
            "signup_welcome": {
                "code": "377204",
                "variables": ("NAME",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_signup_allows_phone_only_registration_with_sms_contact_method(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        response = self.client.post(
            reverse("signup"),
            {
                "full_name": "کاربر موبایل",
                "phone_number": "09123330002",
                "address_street": "خیابان تست",
                "email": "",
                "preferred_contact_methods": ["sms"],
                "telegram_id": "",
                "password1": "Signup@123",
                "password2": "Signup@123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("sms_verification"))

        user = CustomUser.objects.get(phone_number="09123330002")
        self.assertIsNone(user.email)
        self.assertEqual(user.preferred_contact_methods, ["sms"])
        self.assertFalse(user.is_active)
        deliveries = list(NotificationDelivery.objects.order_by("created_at"))
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(
            [item.event for item in deliveries],
            ["accounts.signup.welcome_sms", "accounts.signup.verification_code"],
        )
        self.assertEqual(post_mock.call_count, 2)

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
        self.assertFalse(signup_form.fields["email"].required)

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
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_sms_verification_page_auto_sends_code_once_for_user_phone(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        self.user.preferred_contact_methods = ["sms"]
        self.user.is_active = False
        self.user.save(update_fields=["preferred_contact_methods", "is_active"])
        self.client.force_login(self.user)

        first_response = self.client.get(reverse("sms_verification"))
        second_response = self.client.get(reverse("sms_verification"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(first_response, "09121110000")
        self.assertContains(first_response, "ارسال مجدد کد")
        self.assertContains(first_response, "کد تایید پیامکی برای شما ارسال شد.")
        self.assertEqual(NotificationDelivery.objects.filter(provider="sms").count(), 1)
        post_mock.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_verify_sms_code_activates_authenticated_user(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        self.user.preferred_contact_methods = ["sms"]
        self.user.is_active = False
        self.user.save(update_fields=["preferred_contact_methods", "is_active"])
        otp = SMSVerificationOTP.generate_otp(self.user, "09121110000")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("sms_verification"),
            {
                "action": "verify_code",
                "phone_number": "09121110000",
                "code": otp.code,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("home"))
        otp.refresh_from_db()
        self.assertTrue(otp.is_used)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
        SMS_IR_API_KEY="test-api-key",
        SMS_IR_BASE_URL="https://api.sms.ir",
        SMS_IR_VERIFY_ENDPOINT="/v1/send/verify",
        SMS_PATTERNS={
            "verification": {
                "code": "210072",
                "variables": ("CODE",),
            },
        },
    )
    @patch("notifications.providers.sms.requests.post")
    def test_email_verification_redirects_to_sms_step_when_sms_is_selected(self, post_mock):
        response_mock = Mock()
        response_mock.ok = True
        response_mock.status_code = 200
        response_mock.text = '{"status": 1, "message": "موفق", "data": 778899}'
        response_mock.json.return_value = {
            "status": 1,
            "message": "موفق",
            "data": 778899,
        }
        post_mock.return_value = response_mock

        self.user.email = "combo@example.com"
        self.user.preferred_contact_methods = ["email", "sms"]
        self.user.is_active = False
        self.user.save(update_fields=["email", "preferred_contact_methods", "is_active"])
        self.client.force_login(self.user)
        otp = EmailVerificationOTP.generate_otp(self.user, "combo@example.com")

        response = self.client.post(
            reverse("email_verification"),
            {
                "action": "verify_code",
                "email": "combo@example.com",
                "code": otp.code,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("sms_verification"),
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)

        sms_page = self.client.get(reverse("sms_verification"))
        self.assertEqual(sms_page.status_code, 200)
        self.assertContains(sms_page, "حالا کد تایید پیامکی را وارد کنید.")
        self.assertEqual(NotificationDelivery.objects.filter(provider="sms").count(), 1)
        post_mock.assert_called_once()

    def test_middleware_redirects_pending_sms_verification_users_to_sms_page(self):
        self.user.preferred_contact_methods = ["sms"]
        self.user.is_active = False
        self.user.save(update_fields=["preferred_contact_methods", "is_active"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f'{reverse("sms_verification")}?next=%2F',
            fetch_redirect_response=False,
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
        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        self.assertEqual(len(email_deliveries), 1)
        self.assertEqual(email_deliveries[0].recipients, ["fresh@example.com"])

        previous_otp.refresh_from_db()
        self.assertTrue(previous_otp.is_used)

        latest_otp = EmailVerificationOTP.objects.filter(user=self.user, email="fresh@example.com").first()
        self.assertIsNotNone(latest_otp)
        self.assertFalse(latest_otp.is_used)
        self.assertIn(latest_otp.code, email_deliveries[0].body)

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

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Auction Platform <sender@example.com>",
        SERVER_EMAIL="sender@example.com",
    )
    def test_email_verification_page_auto_sends_code_once_for_user_email(self):
        self.user.email = "autoflow@example.com"
        self.user.save(update_fields=["email"])
        self.client.force_login(self.user)

        first_response = self.client.get(reverse("email_verification"))
        second_response = self.client.get(reverse("email_verification"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(first_response, "autoflow@example.com")
        self.assertContains(first_response, "ارسال مجدد کد")
        self.assertContains(first_response, "کد تایید ۶ رقمی به ایمیل شما ارسال شد.")
        email_deliveries = list(NotificationDelivery.objects.filter(provider='email'))
        self.assertEqual(len(email_deliveries), 1)
        self.assertEqual(email_deliveries[0].recipients, ["autoflow@example.com"])

    def test_verify_email_code_accepts_persian_digits(self):
        self.client.force_login(self.user)
        otp = EmailVerificationOTP.generate_otp(self.user, "persian-code@example.com")
        persian_code = otp.code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

        response = self.client.post(
            reverse("verify_email_code"),
            data=json.dumps({"email": "persian-code@example.com", "code": persian_code}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)
        self.assertEqual(self.user.email, "persian-code@example.com")


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user_sms_only = CustomUser.objects.create_user(
            phone_number="09121111111",
            password="OldPassword@123",
            full_name="کاربر پیامک",
        )
        self.user_sms_only.is_sms_verified = True
        self.user_sms_only.is_email_verified = False
        self.user_sms_only.email = None
        self.user_sms_only.save()

        self.user_email_only = CustomUser.objects.create_user(
            phone_number="09122222222",
            password="OldPassword@123",
            full_name="کاربر ایمیل",
        )
        self.user_email_only.is_sms_verified = False
        self.user_email_only.is_email_verified = True
        self.user_email_only.email = "email_only@example.com"
        self.user_email_only.save()

        self.user_both = CustomUser.objects.create_user(
            phone_number="09123333333",
            password="OldPassword@123",
            full_name="کاربر هردو",
        )
        self.user_both.is_sms_verified = True
        self.user_both.is_email_verified = True
        self.user_both.email = "both@example.com"
        self.user_both.save()

        self.user_neither = CustomUser.objects.create_user(
            phone_number="09124444444",
            password="OldPassword@123",
            full_name="کاربر تایید نشده",
        )
        self.user_neither.is_sms_verified = False
        self.user_neither.is_email_verified = False
        self.user_neither.email = None
        self.user_neither.save()

    def test_non_existent_phone_number_returns_error(self):
        response = self.client.post(
            reverse("password_reset_request"),
            data={"phone_number": "09129999999"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "حساب کاربری با این شماره موبایل در سیستم یافت نشد.")

    @patch("accounts.views.send_password_reset_sms")
    def test_scenario_1_only_phone_verified_sends_sms_and_redirects_to_verify(self, mock_sms):
        response = self.client.post(
            reverse("password_reset_request"),
            data={"phone_number": "09121111111"},
        )
        self.assertRedirects(response, reverse("password_reset_verify"))
        mock_sms.assert_called_once()
        call_kwargs = mock_sms.call_args[1]
        self.assertEqual(call_kwargs["user"], self.user_sms_only)
        self.assertEqual(len(call_kwargs["code"]), 6)

        # Check session
        session = self.client.session
        self.assertEqual(session.get("password_reset_user_id"), str(self.user_sms_only.pk))
        self.assertEqual(session.get("password_reset_channel"), "sms")
        self.assertEqual(session.get("password_reset_otp_code"), call_kwargs["code"])

    @patch("accounts.views.send_password_reset_email")
    def test_scenario_2_only_email_verified_sends_email_and_redirects_to_verify(self, mock_email):
        response = self.client.post(
            reverse("password_reset_request"),
            data={"phone_number": "09122222222"},
        )
        self.assertRedirects(response, reverse("password_reset_verify"))
        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1]
        self.assertEqual(call_kwargs["user"], self.user_email_only)
        self.assertEqual(call_kwargs["email"], "email_only@example.com")
        self.assertEqual(len(call_kwargs["code"]), 6)

        session = self.client.session
        self.assertEqual(session.get("password_reset_user_id"), str(self.user_email_only.pk))
        self.assertEqual(session.get("password_reset_channel"), "email")

    def test_scenario_3_both_verified_redirects_to_choose_channel(self):
        response = self.client.post(
            reverse("password_reset_request"),
            data={"phone_number": "09123333333"},
        )
        self.assertRedirects(response, reverse("password_reset_choose_channel"))
        session = self.client.session
        self.assertEqual(session.get("password_reset_user_id"), str(self.user_both.pk))

    @patch("accounts.views.send_password_reset_sms")
    def test_choose_channel_submits_sms_choice(self, mock_sms):
        session = self.client.session
        session["password_reset_user_id"] = str(self.user_both.pk)
        session.save()

        response = self.client.post(
            reverse("password_reset_choose_channel"),
            data={"channel": "sms"},
        )
        self.assertRedirects(response, reverse("password_reset_verify"))
        mock_sms.assert_called_once()
        self.assertEqual(self.client.session.get("password_reset_channel"), "sms")

    @patch("accounts.views.send_password_reset_email")
    def test_choose_channel_submits_email_choice(self, mock_email):
        session = self.client.session
        session["password_reset_user_id"] = str(self.user_both.pk)
        session.save()

        response = self.client.post(
            reverse("password_reset_choose_channel"),
            data={"channel": "email"},
        )
        self.assertRedirects(response, reverse("password_reset_verify"))
        mock_email.assert_called_once()
        self.assertEqual(self.client.session.get("password_reset_channel"), "email")

    def test_scenario_4_neither_verified_shows_support_guide(self):
        response = self.client.post(
            reverse("password_reset_request"),
            data={"phone_number": "09124444444"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "هیچ‌کدام از اطلاعات تماس")
        self.assertContains(response, "پشتیبانی")

    def test_verify_otp_invalid_code_decrements_attempts(self):
        session = self.client.session
        session["password_reset_user_id"] = str(self.user_sms_only.pk)
        session["password_reset_channel"] = "sms"
        session["password_reset_target"] = "09121111111"
        session["password_reset_otp_code"] = "123456"
        session["password_reset_otp_expires_at"] = 9999999999
        session["password_reset_otp_last_sent_at"] = 0
        session.save()

        response = self.client.post(
            reverse("password_reset_verify"),
            data={"code": "999999", "action": "verify"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "کد وارد شده صحیح نمی‌باشد")

    def test_verify_otp_correct_code_redirects_to_set_password(self):
        session = self.client.session
        session["password_reset_user_id"] = str(self.user_sms_only.pk)
        session["password_reset_channel"] = "sms"
        session["password_reset_target"] = "09121111111"
        session["password_reset_otp_code"] = "654321"
        session["password_reset_otp_expires_at"] = 9999999999
        session["password_reset_otp_last_sent_at"] = 0
        session.save()

        # Supports Persian digits input as well
        persian_code = "۶۵۴۳۲۱"
        response = self.client.post(
            reverse("password_reset_verify"),
            data={"code": persian_code, "action": "verify"},
        )
        self.assertRedirects(response, reverse("password_reset_set_password"))
        self.assertIsNotNone(self.client.session.get("password_reset_verified_token"))
        self.assertIsNone(self.client.session.get("password_reset_otp_code"))

    def test_set_password_updates_user_password_and_redirects_to_login(self):
        from django.core import signing
        import time

        token = signing.dumps(
            {"user_id": str(self.user_sms_only.pk), "verified_at": time.time()},
            salt="password-reset-verified",
        )
        session = self.client.session
        session["password_reset_user_id"] = str(self.user_sms_only.pk)
        session["password_reset_verified_token"] = token
        session.save()

        response = self.client.post(
            reverse("password_reset_set_password"),
            data={
                "new_password": "NewSecretPassword@2026",
                "confirm_password": "NewSecretPassword@2026",
            },
        )
        self.assertRedirects(response, reverse("login"))

        self.user_sms_only.refresh_from_db()
        self.assertTrue(self.user_sms_only.check_password("NewSecretPassword@2026"))

        # Session should be wiped of reset data
        self.assertIsNone(self.client.session.get("password_reset_user_id"))
        self.assertIsNone(self.client.session.get("password_reset_verified_token"))

    def test_login_page_contains_password_reset_link(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("password_reset_request"))
