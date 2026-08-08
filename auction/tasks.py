from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging

from django.contrib.auth import get_user_model
try:
    from celery import shared_task
except ImportError:
    def shared_task(func):
        func.delay = func

        def _apply_async(args=None, kwargs=None, eta=None, **options):
            if eta is not None:
                return None
            call_args = tuple(args or ())
            call_kwargs = dict(kwargs or {})
            return func(*call_args, **call_kwargs)

        func.apply_async = _apply_async
        return func

from django.utils import timezone

from core.emailing import get_user_email_recipients, send_plain_email
from notifications.enums import NotificationProviderType
from notifications.services import notification_service

from .models import Auction
from .services import ensure_products_have_finished_winners


logger = logging.getLogger(__name__)


def get_active_users_emails():
    return get_user_email_recipients()


def get_active_users_for_notifications():
    user_model = get_user_model()
    return list(user_model.objects.filter(is_active=True))


def _get_user_notification_providers(user):
    providers = []
    if str(getattr(user, 'email', '') or '').strip():
        providers.append(NotificationProviderType.EMAIL)
    if str(getattr(user, 'phone_number', '') or '').strip():
        providers.append(NotificationProviderType.SMS)
    return providers


def _parse_expected_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _scheduled_datetime_matches(actual_value, expected_value):
    expected_dt = _parse_expected_datetime(expected_value)
    if expected_dt is None or actual_value is None:
        return True
    delta = abs((actual_value - expected_dt).total_seconds())
    return delta < 1


def _is_within_delivery_window(target_time, *, late_grace_seconds=300):
    if target_time is None:
        return False
    now = timezone.now()
    earliest_allowed = target_time - timezone.timedelta(seconds=1)
    latest_allowed = target_time + timezone.timedelta(seconds=late_grace_seconds)
    return earliest_allowed <= now <= latest_allowed


def _claim_dispatch(auction_id, field_name):
    claimed_at = timezone.now()
    updated = Auction.objects.filter(pk=auction_id, **{f"{field_name}__isnull": True}).update(
        **{field_name: claimed_at}
    )
    if updated:
        return claimed_at
    return None


def _release_dispatch(auction_id, field_name, claimed_at):
    if claimed_at is None:
        return
    Auction.objects.filter(pk=auction_id, **{field_name: claimed_at}).update(**{field_name: None})


def _format_amount(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal('0')
    return f"{int(amount):,}"


def _format_datetime(value):
    if not value:
        return '-'
    localized = timezone.localtime(value)
    return localized.strftime('%Y/%m/%d %H:%M')


@shared_task
def send_auction_starting_soon_email(auction_id, expected_start=None):
    """Sent 24 hours before auction starts."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.start_date, expected_start):
        return

    if not _is_within_delivery_window(auction.start_date - timezone.timedelta(hours=24)):
        return

    claimed_at = _claim_dispatch(auction.id, 'start_reminder_24h_dispatched_at')
    if claimed_at is None:
        return

    subject = f"یادآوری: ۲۴ ساعت تا شروع مزایده «{auction.name}»"
    message = f"""سلام،

مزایده «{auction.name}» ۲۴ ساعت دیگر آغاز می‌شود.

زمان شروع: {_format_datetime(auction.start_date)}

اگر قصد شرکت در این مزایده را دارید، لطفاً از آماده بودن حساب کاربری و اعتبار خود مطمئن شوید.

با آرزوی موفقیت
تیم ماه آکشن"""
    try:
        users = get_active_users_for_notifications()
        for user in users:
            providers = _get_user_notification_providers(user)
            if not providers:
                continue
            notification_service.send_template(
                event='auction.start.reminder_24h',
                template='auction_24h',
                providers=providers,
                user=user,
                context={
                    'auction_name': auction.name,
                    'auction_start_date': _format_datetime(auction.start_date),
                },
                metadata={
                    'auction_id': str(auction.pk),
                    'user_id': str(user.pk),
                },
            )
    except Exception:
        _release_dispatch(auction.id, 'start_reminder_24h_dispatched_at', claimed_at)
        logger.exception("Starting-soon email failed for auction %s", auction.pk)


@shared_task
def send_auction_started_email(auction_id, expected_start=None):
    """Sent exactly when auction starts."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.start_date, expected_start):
        return

    if not _is_within_delivery_window(auction.start_date):
        return

    claimed_at = _claim_dispatch(auction.id, 'start_notice_dispatched_at')
    if claimed_at is None:
        return

    subject = f"زمان رقابت فرا رسید؛ مزایده «{auction.name}» آغاز شد"
    message = f"""سلام،

مزایده «{auction.name}» هم‌اکنون آغاز شده است.

از این لحظه امکان ثبت پیشنهاد قیمت و شرکت در رقابت برای آثار این مزایده فعال است.

با آرزوی موفقیت
تیم ماه آکشن"""
    try:
        users = get_active_users_for_notifications()
        for user in users:
            providers = _get_user_notification_providers(user)
            if not providers:
                continue
            notification_service.send_template(
                event='auction.start.started',
                template='auction_started',
                providers=providers,
                user=user,
                context={
                    'auction_name': auction.name,
                },
                metadata={
                    'auction_id': str(auction.pk),
                    'user_id': str(user.pk),
                },
            )
    except Exception:
        _release_dispatch(auction.id, 'start_notice_dispatched_at', claimed_at)
        logger.exception("Started email failed for auction %s", auction.pk)


@shared_task
def send_auction_ending_soon_email(auction_id, expected_end=None):
    """Sent 12 hours before auction ends."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.end_date, expected_end):
        return

    if not _is_within_delivery_window(auction.end_date - timezone.timedelta(hours=12)):
        return

    claimed_at = _claim_dispatch(auction.id, 'end_reminder_12h_dispatched_at')
    if claimed_at is None:
        return

    emails = get_active_users_emails()
    if not emails:
        return

    subject = f"یادآوری: ۱۲ ساعت تا پایان مزایده «{auction.name}»"
    message = f"""سلام،

مزایده «{auction.name}» تنها ۱۲ ساعت دیگر به پایان می‌رسد.

زمان پایان: {_format_datetime(auction.end_date)}

اگر قصد دارید پیشنهاد جدیدی ثبت کنید یا آخرین وضعیت رقابت را بررسی کنید، اکنون زمان مناسبی است.

با سپاس
تیم ماه آکشن"""
    try:
        send_plain_email(
            event='auction.end.reminder_12h',
            subject=subject,
            message=message,
            recipients=emails,
            fail_silently=False,
            metadata={'auction_id': str(auction.pk)},
        )
    except Exception:
        _release_dispatch(auction.id, 'end_reminder_12h_dispatched_at', claimed_at)
        logger.exception("Ending-soon email failed for auction %s", auction.pk)


@shared_task
def send_auction_extended_email(auction_id, previous_end=None, expected_end=None):
    """Sent immediately when the auction end time is extended."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.end_date, expected_end):
        return

    emails = get_active_users_emails()
    if not emails:
        return

    previous_end_dt = _parse_expected_datetime(previous_end)
    subject = f"مهلت مزایده «{auction.name}» تمدید شد"
    message = f"""سلام،

مهلت پایان مزایده «{auction.name}» تمدید شد.

پایان قبلی: {_format_datetime(previous_end_dt)}
پایان جدید: {_format_datetime(auction.end_date)}

برای ثبت پیشنهاد یا پیگیری آخرین وضعیت مزایده می‌توانید دوباره وارد سامانه شوید.

با سپاس
تیم ماه آکشن"""
    try:
        send_plain_email(
            event='auction.end.extended',
            subject=subject,
            message=message,
            recipients=emails,
            fail_silently=True,
            metadata={
                'auction_id': str(auction.pk),
                'previous_end': previous_end,
            },
        )
    except Exception:
        pass


@shared_task
def send_auction_ended_email(auction_id, expected_end=None):
    """Sent when the auction ends and includes winner billing details."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.end_date, expected_end):
        return

    if timezone.now() + timezone.timedelta(seconds=1) < auction.end_date:
        return

    emails = get_active_users_emails()
    end_notice_claimed_at = _claim_dispatch(auction.id, 'end_notice_dispatched_at')
    if emails:
        subject = f"مزایده «{auction.name}» به پایان رسید"
        message = f"""سلام،

مزایده «{auction.name}» به پایان رسید.

نتایج نهایی این مزایده ثبت شده است و کاربران برنده، ایمیل صورتحساب و فاکتور اولیه خود را دریافت می‌کنند.

با سپاس
تیم ماه آکشن"""
        if end_notice_claimed_at is not None:
            try:
                send_plain_email(
                    event='auction.end.finished',
                    subject=subject,
                    message=message,
                    recipients=emails,
                    fail_silently=False,
                    metadata={'auction_id': str(auction.pk)},
                )
            except Exception:
                _release_dispatch(auction.id, 'end_notice_dispatched_at', end_notice_claimed_at)
                logger.exception("Ended email failed for auction %s", auction.pk)
                return

    products = ensure_products_have_finished_winners(
        auction.products.select_related('winner').all()
    )
    billing_claimed_at = _claim_dispatch(auction.id, 'winner_billing_dispatched_at')
    if billing_claimed_at is None:
        return
    winners_map = defaultdict(list)
    for product in products:
        winner = getattr(product, 'winner', None)
        winner_email = getattr(winner, 'email', None)
        if winner and winner_email:
            winners_map[winner.pk].append(product)

    for product_list in winners_map.values():
        winner = product_list[0].winner
        display_name = (
            getattr(winner, 'get_full_name', lambda: '')()
            or getattr(winner, 'full_name', '')
            or 'کاربر گرامی'
        )
        line_items = []
        total_amount = Decimal('0')
        for product in product_list:
            product_total = Decimal(str(product.current_price or 0))
            total_amount += product_total
            lot_label = f"لات {product.lot}" if product.lot else f"کد {product.product_id}"
            line_items.append(
                f"- {product.title} ({lot_label}) | مبلغ نهایی: {_format_amount(product_total)} تومان"
            )

        line_items_text = '\n'.join(line_items)
        subject = f"نتیجه مزایده و صورتحساب اولیه «{auction.name}»"
        message = f"""سلام {display_name}،

مزایده «{auction.name}» به پایان رسیده و شما برنده نهایی مورد یا موارد زیر شده‌اید:

{line_items_text}

جمع کل صورتحساب اولیه: {_format_amount(total_amount)} تومان

این مبلغ بر اساس قیمت نهایی ثبت‌شده در مزایده محاسبه شده و فاکتور اولیه شما محسوب می‌شود.

با سپاس
تیم ماه آکشن"""
        try:
            send_plain_email(
                event='auction.winner.billing',
                subject=subject,
                message=message,
                recipients=[winner.email],
                fail_silently=False,
                metadata={
                    'auction_id': str(auction.pk),
                    'winner_id': str(winner.pk),
                },
            )
        except Exception:
            _release_dispatch(auction.id, 'winner_billing_dispatched_at', billing_claimed_at)
            logger.exception("Winner billing email failed for auction %s", auction.pk)
            return
