import datetime
import logging
import os
import threading

import pytz
import requests
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from django.contrib.auth import get_user_model
from core.utils import send_admin_notification
from .models import CreditIncreaseRequest, VerificationRequest
from .realtime import broadcast_profile_update


logger = logging.getLogger(__name__)

@receiver(post_save, sender=get_user_model())
def on_user_save(sender, instance, **kwargs):
    """
    بروزرسانی پروفایل کاربر به صورت زنده در صورت تغییر در مدل کاربر
    """
    transaction.on_commit(lambda: broadcast_profile_update(instance.pk))

BOT_TOKEN = (
    getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    or getattr(settings, 'BOT_TOKEN', None)
    or os.environ.get('TELEGRAM_BOT_TOKEN')
    or os.environ.get('BOT_TOKEN')
)
ADMIN_GROUP_CHAT_ID = (
    getattr(settings, 'ADMIN_GROUP_CHAT_ID', None)
    or getattr(settings, 'TELEGRAM_CHAT_ID', None)
    or os.environ.get('TELEGRAM_CHAT_ID')
)
try:
    ADMIN_GROUP_CHAT_ID = int(ADMIN_GROUP_CHAT_ID)
except (TypeError, ValueError):
    ADMIN_GROUP_CHAT_ID = None

_raw_auction_message_thread_id = (
    getattr(settings, 'TELEGRAM_AUCTION_MESSAGE_THREAD_ID', None)
    or os.environ.get('TELEGRAM_AUCTION_MESSAGE_THREAD_ID')
    or 11
)
try:
    AUCTION_MESSAGE_THREAD_ID = int(_raw_auction_message_thread_id)
except (TypeError, ValueError):
    AUCTION_MESSAGE_THREAD_ID = None

_raw_credit_message_thread_id = (
    getattr(settings, 'TELEGRAM_CREDIT_MESSAGE_THREAD_ID', None)
    or os.environ.get('TELEGRAM_CREDIT_MESSAGE_THREAD_ID')
    or AUCTION_MESSAGE_THREAD_ID
)
try:
    CREDIT_MESSAGE_THREAD_ID = int(_raw_credit_message_thread_id)
except (TypeError, ValueError):
    CREDIT_MESSAGE_THREAD_ID = None


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


def _send_auction_verification_message(message_text: str) -> None:
    _send_telegram_message(
        message_text,
        thread_id=AUCTION_MESSAGE_THREAD_ID,
        log_prefix="Auction verification",
    )


def _send_credit_increase_message(message_text: str) -> None:
    _send_telegram_message(
        message_text,
        thread_id=CREDIT_MESSAGE_THREAD_ID,
        log_prefix="Credit increase",
    )


def _handle_verification_request_side_effects_async(
    *,
    request_id: int,
    user_id,
    user_label: str,
    full_name: str,
    phone_number: str,
    created_at: str,
) -> None:
    def runner() -> None:
        try:
            send_admin_notification(
                notification_type='verification_request',
                title='درخواست جدید تایید مزایده',
                message=f'یک درخواست تایید مزایده توسط {user_label} ثبت شد.',
                data={'request_type': 'verification', 'id': request_id, 'user_id': user_id},
            )
        except Exception:
            logger.exception("Auction verification admin notification exception")

        message_text = "\n".join(
            [
                "🎨 <b>درخواست جدید شرکت در مزایده</b>",
                "",
                f"👤 <b>نام کاربر:</b> {full_name}",
                f"📱 <b>شماره تلفن:</b> {phone_number}",
                f"🆔 <b>شناسه درخواست:</b> {request_id}",
                f"🕒 <b>تاریخ و ساعت:</b> {created_at}",
            ]
        )
        _send_auction_verification_message(message_text)

    threading.Thread(target=runner, daemon=True).start()


def _handle_credit_request_side_effects_async(
    *,
    request_id: int,
    user_id,
    user_label: str,
    current_credit,
    phone_number: str,
    created_at: str,
) -> None:
    def runner() -> None:
        try:
            send_admin_notification(
                notification_type='credit_request',
                title='درخواست جدید افزایش اعتبار',
                message=f'یک درخواست افزایش اعتبار توسط {user_label} ثبت شد.',
                data={'request_type': 'credit', 'id': request_id, 'user_id': user_id},
            )
        except Exception:
            logger.exception("Credit request admin notification exception")

        amount_label = f"{current_credit:,}" if current_credit is not None else "0"
        message_text = "\n".join(
            [
                "💳 <b>درخواست جدید افزایش اعتبار</b>",
                "",
                f"👤 <b>نام کاربر:</b> {user_label}",
                f"📱 <b>شماره تلفن:</b> {phone_number}",
                f"💰 <b>اعتبار فعلی/درخواستی:</b> {amount_label} دلار",
                f"🆔 <b>شناسه درخواست:</b> {request_id}",
                f"🕒 <b>تاریخ و ساعت:</b> {created_at}",
            ]
        )
        _send_credit_increase_message(message_text)

    threading.Thread(target=runner, daemon=True).start()


@receiver(post_save, sender=VerificationRequest)
def sync_verification_to_user(sender, instance, created=False, **kwargs):
    user = instance.user
    if user.is_verified != instance.is_verified:
        user.is_verified = instance.is_verified
        user.save(update_fields=["is_verified"])

    if created:
        user_label = (getattr(user, "get_full_name", lambda: "")() or "").strip() or getattr(
            user, "phone_number", ""
        )
        full_name = (instance.full_name or "").strip() or user_label
        phone_number = (instance.phone_number or "").strip() or getattr(user, "phone_number", "")
        created_at = _jalali_datetime_str(instance.created_at or timezone.now())
        transaction.on_commit(
            lambda: _handle_verification_request_side_effects_async(
                request_id=instance.pk,
                user_id=instance.user_id,
                user_label=user_label,
                full_name=full_name,
                phone_number=phone_number,
                created_at=created_at,
            )
        )


@receiver(post_save, sender=CreditIncreaseRequest)
def notify_credit_increase_request(sender, instance, created=False, **kwargs):
    if not created:
        return

    user = instance.user
    user_label = (getattr(user, "get_full_name", lambda: "")() or "").strip() or getattr(
        user, "phone_number", ""
    )
    phone_number = (getattr(user, "phone_number", "") or "").strip()
    created_at = _jalali_datetime_str(instance.created_at or timezone.now())
    transaction.on_commit(
        lambda: _handle_credit_request_side_effects_async(
            request_id=instance.pk,
            user_id=instance.user_id,
            user_label=user_label,
            current_credit=instance.current_credit,
            phone_number=phone_number,
            created_at=created_at,
        )
    )
