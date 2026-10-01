from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import CustomUser
from store.middleware import VisitTrackingMiddleware
from store.models import SiteVisitLog
from store.user_agents import detect_operating_system


class OperatingSystemDetectionTests(TestCase):
    def test_detect_operating_system_extracts_common_platforms(self):
        cases = [
            (
                "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240505.005) AppleWebKit/537.36 Chrome/125.0.0.0 Mobile Safari/537.36",
                "Android 14",
            ),
            (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1",
                "iOS 17.5.1",
            ),
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
                "Windows 10/11 (NT 10.0)",
            ),
        ]

        for user_agent, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(detect_operating_system(user_agent), expected)

    def test_visit_tracking_middleware_saves_detected_operating_system(self):
        request = RequestFactory().get(
            "/products/test/",
            HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240505.005) AppleWebKit/537.36 Chrome/125.0.0.0 Mobile Safari/537.36",
            REMOTE_ADDR="127.0.0.1",
        )
        SessionMiddleware(lambda req: HttpResponse("ok")).process_request(request)
        request.user = AnonymousUser()

        response = VisitTrackingMiddleware(lambda req: HttpResponse("ok"))(request)

        self.assertEqual(response.status_code, 200)
        visit_log = SiteVisitLog.objects.get()
        self.assertEqual(visit_log.operating_system, "Android 14")


class UserHistoryOperatingSystemTests(TestCase):
    def setUp(self):
        self.admin_user = CustomUser.objects.create_user(
            phone_number="09120000111",
            password="Admin@1234",
            full_name="ادمین تست",
            is_staff=True,
        )
        self.normal_user = CustomUser.objects.create_user(
            phone_number="09120000112",
            password="User@1234",
            full_name="کاربر تست",
        )
        self.client.force_login(self.admin_user)

    def test_user_history_api_returns_operating_system_for_site_visits(self):
        SiteVisitLog.objects.create(
            user=self.normal_user,
            session_key="session-with-os",
            ip_address="127.0.0.1",
            operating_system="Android 14",
        )

        response = self.client.get(
            reverse("admin_panel:users-history-api", args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["site_visit_history"][0]["operating_system"], "Android 14")
        self.assertEqual(payload["activity_timeline"][0]["operating_system"], "Android 14")

    def test_user_history_api_keeps_operating_system_blank_for_old_records(self):
        SiteVisitLog.objects.create(
            user=self.normal_user,
            session_key="session-without-os",
            ip_address="127.0.0.1",
        )

        response = self.client.get(
            reverse("admin_panel:users-history-api", args=[self.normal_user.pk]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["site_visit_history"][0]["operating_system"], "")
        self.assertEqual(payload["activity_timeline"][0]["operating_system"], "")
