import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse


class Command(BaseCommand):
    help = "ثبت webhook ربات تلگرام برای دکمه‌های درخواست خرید"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            dest="base_url",
            help="آدرس عمومی پروژه مثل https://example.com",
        )
        parser.add_argument(
            "--drop-pending-updates",
            action="store_true",
            help="در زمان ثبت webhook، آپدیت‌های معوق تلگرام حذف شوند",
        )

    def handle(self, *args, **options):
        bot_token = (
            getattr(settings, "TELEGRAM_BOT_TOKEN", None)
            or getattr(settings, "BOT_TOKEN", None)
            or os.environ.get("TELEGRAM_BOT_TOKEN")
            or os.environ.get("BOT_TOKEN")
        )
        if not bot_token:
            raise CommandError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")

        base_url = (
            options.get("base_url")
            or getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", None)
            or os.environ.get("TELEGRAM_WEBHOOK_BASE_URL")
        )
        if not base_url:
            raise CommandError("base URL مشخص نیست. از --base-url یا TELEGRAM_WEBHOOK_BASE_URL استفاده کن.")

        base_url = str(base_url).strip().rstrip("/")
        webhook_path = reverse("store:telegram_purchase_webhook")
        webhook_url = f"{base_url}{webhook_path}"

        payload = {
            "url": webhook_url,
            "allowed_updates": ["callback_query"],
            "drop_pending_updates": bool(options.get("drop_pending_updates")),
        }

        secret_token = (
            getattr(settings, "TELEGRAM_WEBHOOK_SECRET_TOKEN", None)
            or os.environ.get("TELEGRAM_WEBHOOK_SECRET_TOKEN")
        )
        if secret_token:
            payload["secret_token"] = secret_token

        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json=payload,
            timeout=15,
        )

        if response.status_code >= 400:
            raise CommandError(f"خطا در setWebhook: {response.status_code} {response.text[:500]}")

        data = response.json()
        if not data.get("ok"):
            raise CommandError(f"تلگرام webhook را نپذیرفت: {data}")

        self.stdout.write(self.style.SUCCESS("webhook با موفقیت ثبت شد."))
        self.stdout.write(f"Webhook URL: {webhook_url}")
