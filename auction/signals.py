import datetime
import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from notifications.enums import NotificationProviderType
from notifications.services import notification_service

from .models import Bid, Auction
from .tasks import (
    send_auction_starting_soon_email,
    send_auction_started_email,
    send_auction_ending_soon_email,
    send_auction_extended_email,
    send_auction_ended_email,
)


logger = logging.getLogger(__name__)
_BID_EMAIL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='bid-email')


def _send_bid_notification_emails(bid_id):
    bid = (
        Bid.objects
        .select_related('user', 'product')
        .filter(pk=bid_id)
        .first()
    )
    if bid is None:
        return

    current_user = bid.user
    product_title = getattr(bid.product, 'title', bid.product.product_id)

    providers = []
    if str(getattr(current_user, 'email', '') or '').strip():
        providers.append(NotificationProviderType.EMAIL)
    if str(getattr(current_user, 'phone_number', '') or '').strip():
        providers.append(NotificationProviderType.SMS)
    if providers:
        display_name = (
            getattr(current_user, 'get_full_name', lambda: '')()
            or getattr(current_user, 'full_name', '')
            or bid.user_fullname
            or 'کاربر گرامی'
        )
        try:
            notification_service.send_template(
                event='auction.bid.confirmed',
                template='add_bid',
                providers=providers,
                user=current_user,
                context={
                    'name': display_name,
                    'product_title': product_title,
                    'formatted_bid_amount': f'{bid.bid_amount:,}',
                    'lot_number': getattr(bid.product, 'lot', '') or getattr(bid.product, 'product_id', '') or '',
                    'auction_name': getattr(getattr(bid.product, 'auction', None), 'name', '') or '',
                },
                metadata={'bid_id': str(bid.pk)},
            )
        except Exception:
            logger.exception("Bid confirmation notification failed for bid %s", bid.pk)

    previous_highest_bid = (
        Bid.objects
        .select_related('user')
        .filter(product=bid.product)
        .exclude(id=bid.id)
        .order_by('-bid_amount', '-created_at')
        .first()
    )

    if not previous_highest_bid:
        return

    previous_user = previous_highest_bid.user
    if previous_user.id == current_user.id:
        return

    providers = []
    if str(getattr(previous_user, 'email', '') or '').strip():
        providers.append(NotificationProviderType.EMAIL)
    if str(getattr(previous_user, 'phone_number', '') or '').strip():
        providers.append(NotificationProviderType.SMS)
    if not providers:
        return

    display_name = (
        getattr(previous_user, 'get_full_name', lambda: '')()
        or getattr(previous_user, 'full_name', '')
        or previous_highest_bid.user_fullname
        or 'کاربر گرامی'
    )
    try:
        notification_service.send_template(
            event='auction.bid.outbid',
            template='dell_bid',
            providers=providers,
            user=previous_user,
            context={
                'name': display_name,
                'product_title': product_title,
                'formatted_latest_bid_amount': f'{bid.bid_amount:,}',
            },
            metadata={
                'previous_bid_id': str(previous_highest_bid.pk),
                'latest_bid_id': str(bid.pk),
            },
        )
    except Exception:
        logger.exception("Outbid notification failed for bid %s", bid.pk)


def _enqueue_bid_notification_emails(bid_id):
    try:
        _BID_EMAIL_EXECUTOR.submit(_send_bid_notification_emails, bid_id)
    except Exception:
        logger.exception("Bid email queue submit failed for bid %s", bid_id)


@receiver(pre_save, sender=Auction)
def capture_previous_auction_dates(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        previous = Auction.objects.get(pk=instance.pk)
    except Auction.DoesNotExist:
        return
    instance._previous_start_date = previous.start_date
    instance._previous_end_date = previous.end_date


@receiver(post_save, sender=Auction)
def schedule_auction_emails(sender, instance, created, **kwargs):
    """
    Schedules auction emails based on the current start/end dates.
    Old ETA tasks are not revoked, so tasks validate the expected datetime
    again when they run and skip stale schedules automatically.
    """
    now = timezone.now()
    expected_start = instance.start_date.isoformat() if instance.start_date else None
    expected_end = instance.end_date.isoformat() if instance.end_date else None

    # 1. Email: 24 hours before auction starts
    if instance.start_date:
        start_minus_24h = instance.start_date - datetime.timedelta(hours=24)
        if start_minus_24h > now:
            send_auction_starting_soon_email.apply_async(
                args=(instance.id,),
                kwargs={'expected_start': expected_start},
                eta=start_minus_24h,
            )

    # 2. Email: Exactly when the auction starts
    if instance.start_date:
        if instance.start_date > now:
            send_auction_started_email.apply_async(
                args=(instance.id,),
                kwargs={'expected_start': expected_start},
                eta=instance.start_date,
            )

    # 3. Email: 12 hours before the auction ends
    if instance.end_date:
        end_minus_12h = instance.end_date - datetime.timedelta(hours=12)
        if end_minus_12h > now:
            send_auction_ending_soon_email.apply_async(
                args=(instance.id,),
                kwargs={'expected_end': expected_end},
                eta=end_minus_12h,
            )

        if instance.end_date > now:
            send_auction_ended_email.apply_async(
                args=(instance.id,),
                kwargs={'expected_end': expected_end},
                eta=instance.end_date,
            )

    previous_end_date = getattr(instance, '_previous_end_date', None)
    if (
        not created
        and previous_end_date
        and instance.end_date
        and instance.end_date > previous_end_date
    ):
        send_auction_extended_email.delay(
            instance.id,
            previous_end=previous_end_date.isoformat(),
            expected_end=expected_end,
        )


@receiver(post_save, sender=Bid)
def notify_bid_updates(sender, instance, created, **kwargs):
    if not created:
        return

    transaction.on_commit(lambda bid_id=instance.pk: _enqueue_bid_notification_emails(bid_id))
