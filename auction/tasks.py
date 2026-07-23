from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

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

from .models import Auction
from .services import ensure_products_have_finished_winners


def get_active_users_emails():
    return get_user_email_recipients()


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

    emails = get_active_users_emails()
    if not emails:
        return

    subject = f"یادآوری: ۲۴ ساعت تا شروع مزایده «{auction.name}»"
    message = f"""سلام،

مزایده «{auction.name}» ۲۴ ساعت دیگر آغاز می‌شود.

زمان شروع: {_format_datetime(auction.start_date)}

اگر قصد شرکت در این مزایده را دارید، لطفاً از آماده بودن حساب کاربری و اعتبار خود مطمئن شوید.

با آرزوی موفقیت
تیم ماه آکشن"""
    try:
        send_plain_email(subject=subject, message=message, recipients=emails, fail_silently=True)
    except Exception:
        pass


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

    emails = get_active_users_emails()
    if not emails:
        return

    subject = f"زمان رقابت فرا رسید؛ مزایده «{auction.name}» آغاز شد"
    message = f"""سلام،

مزایده «{auction.name}» هم‌اکنون آغاز شده است.

از این لحظه امکان ثبت پیشنهاد قیمت و شرکت در رقابت برای آثار این مزایده فعال است.

با آرزوی موفقیت
تیم ماه آکشن"""
    try:
        send_plain_email(subject=subject, message=message, recipients=emails, fail_silently=True)
    except Exception:
        pass


@shared_task
def send_auction_ending_soon_email(auction_id, expected_end=None):
    """Sent 12 hours before auction ends."""
    try:
        auction = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        return

    if not _scheduled_datetime_matches(auction.end_date, expected_end):
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
        send_plain_email(subject=subject, message=message, recipients=emails, fail_silently=True)
    except Exception:
        pass


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
        send_plain_email(subject=subject, message=message, recipients=emails, fail_silently=True)
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
    if emails:
        subject = f"مزایده «{auction.name}» به پایان رسید"
        message = f"""سلام،

مزایده «{auction.name}» به پایان رسید.

نتایج نهایی این مزایده ثبت شده است و کاربران برنده، ایمیل صورتحساب و فاکتور اولیه خود را دریافت می‌کنند.

با سپاس
تیم ماه آکشن"""
        try:
            send_plain_email(subject=subject, message=message, recipients=emails, fail_silently=True)
        except Exception:
            pass

    products = ensure_products_have_finished_winners(
        auction.products.select_related('winner').all()
    )
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
                subject=subject,
                message=message,
                recipients=[winner.email],
                fail_silently=True,
            )
        except Exception:
            pass
