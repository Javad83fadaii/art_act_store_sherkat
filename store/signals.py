import threading
import logging
import pytz
import datetime
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings
import requests

from core.utils import send_admin_notification
from .models import TelegramPurchaseRequest

logger = logging.getLogger(__name__)

BOT_TOKEN = (
    getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    or getattr(settings, 'BOT_TOKEN', None)
)
ADMIN_GROUP_CHAT_ID = (
    getattr(settings, 'ADMIN_GROUP_CHAT_ID', None)
    or getattr(settings, 'TELEGRAM_CHAT_ID', None)
)
try:
    ADMIN_GROUP_CHAT_ID = int(ADMIN_GROUP_CHAT_ID)
except (TypeError, ValueError):
    ADMIN_GROUP_CHAT_ID = None

STORE_MESSAGE_THREAD_ID = getattr(settings, 'TELEGRAM_STORE_MESSAGE_THREAD_ID', None)
try:
    STORE_MESSAGE_THREAD_ID = int(STORE_MESSAGE_THREAD_ID)
except (TypeError, ValueError):
    STORE_MESSAGE_THREAD_ID = None


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )

    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def _jalali_datetime_str(dt: datetime.datetime) -> str:
    tehran_tz = pytz.timezone("Asia/Tehran")
    dt_local = dt.astimezone(tehran_tz)
    jy, jm, jd = _gregorian_to_jalali(dt_local.year, dt_local.month, dt_local.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {dt_local:%H:%M:%S}"


def _send_telegram_message(message_text: str, *, thread_id: int | None, log_prefix: str) -> None:
    try:
        if BOT_TOKEN and ADMIN_GROUP_CHAT_ID:
            telegram_api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': ADMIN_GROUP_CHAT_ID,
                'text': message_text,
                'parse_mode': 'HTML',
            }
            if thread_id:
                payload['message_thread_id'] = thread_id

            resp = requests.post(telegram_api_url, json=payload, timeout=8)
            if resp.status_code >= 400:
                logger.warning(
                    "%s Telegram sendMessage failed: status=%s body=%s",
                    log_prefix,
                    resp.status_code,
                    resp.text[:300],
                )
            else:
                logger.info(
                    "%s Telegram sendMessage ok: chat_id=%s thread_id=%s",
                    log_prefix,
                    ADMIN_GROUP_CHAT_ID,
                    thread_id,
                )
        else:
            logger.warning(
                "%s Telegram config missing: BOT_TOKEN=%s ADMIN_GROUP_CHAT_ID=%s",
                log_prefix,
                bool(BOT_TOKEN),
                bool(ADMIN_GROUP_CHAT_ID),
            )
    except Exception:
        logger.exception("%s Telegram sendMessage exception", log_prefix)


def _handle_purchase_request_side_effects_async(
    *,
    request_id: int,
    user_id,
    user_label: str,
    product_title: str,
    product_id: str,
    created_at: str,
) -> None:
    def runner() -> None:
        try:
            send_admin_notification(
                notification_type='purchase_request',
                title='درخواست جدید خرید',
                message=f'یک درخواست خرید توسط {user_label} برای «{product_title}» ثبت شد.',
                data={'request_type': 'purchase', 'id': request_id, 'user_id': user_id, 'product_id': product_id},
            )
        except Exception:
            logger.exception("Purchase request admin notification exception")

        message_text = "\n".join(
            [
                "🛍️ <b>درخواست جدید خرید</b>",
                "",
                f"👤 <b>نام کاربر:</b> {user_label}",
                f"🎨 <b>محصول:</b> {product_title}",
                f"🆔 <b>شناسه محصول:</b> {product_id}",
                f"🆔 <b>شناسه درخواست:</b> {request_id}",
                f"🕒 <b>تاریخ و ساعت:</b> {created_at}",
            ]
        )
        _send_telegram_message(message_text, thread_id=STORE_MESSAGE_THREAD_ID, log_prefix="Purchase request")

    threading.Thread(target=runner, daemon=True).start()


@receiver(post_save, sender=TelegramPurchaseRequest)
def notify_purchase_request(sender, instance, created=False, **kwargs):
    if not created:
        return

    user = instance.user
    user_label = (
        (getattr(user, 'get_full_name', lambda: '')() or '').strip()
        or getattr(user, 'phone_number', '')
    )
    product_title = instance.artwork.title if instance.artwork else 'نامشخص'
    product_id = instance.artwork.product_id if instance.artwork else '—'
    created_at = _jalali_datetime_str(instance.created_at or timezone.now())
    transaction.on_commit(
        lambda: _handle_purchase_request_side_effects_async(
            request_id=instance.pk,
            user_id=instance.user_id,
            user_label=user_label,
            product_title=product_title,
            product_id=product_id,
            created_at=created_at,
        )
    )
