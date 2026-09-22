import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Auction
from .tasks import (
    send_auction_ended_email,
    send_auction_extended_notice_sms,
    send_auction_started_email,
    send_auction_starting_soon_email,
)


logger = logging.getLogger(__name__)


def dispatch_due_auction_emails(*, limit=10):
    now = timezone.now()
    dispatched = 0

    dispatched += _dispatch_starting_soon(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_started(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_extension_notice(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_ended(now=now, remaining=max(limit - dispatched, 0))

    return dispatched


def _dispatch_starting_soon(*, now, remaining):
    if remaining <= 0:
        return 0

    upper_bound = now + timedelta(hours=24, seconds=1)
    auctions = Auction.objects.filter(
        start_reminder_24h_dispatched_at__isnull=True,
        start_date__gt=now,
        start_date__lte=upper_bound,
    ).order_by('start_date')[:remaining]

    count = 0
    for auction in auctions:
        try:
            send_auction_starting_soon_email(
                auction.id,
                expected_start=auction.start_date.isoformat(),
            )
            count += 1
        except Exception:
            logger.exception("Dispatch starting-soon email failed for auction %s", auction.pk)
    return count


def _dispatch_started(*, now, remaining):
    if remaining <= 0:
        return 0

    auctions = Auction.objects.filter(
        start_notice_dispatched_at__isnull=True,
        start_date__lte=now + timedelta(seconds=1),
        end_date__gt=now,
    ).order_by('start_date')[:remaining]

    count = 0
    for auction in auctions:
        try:
            send_auction_started_email(
                auction.id,
                expected_start=auction.start_date.isoformat(),
            )
            count += 1
        except Exception:
            logger.exception("Dispatch started email failed for auction %s", auction.pk)
    return count


def _dispatch_extension_notice(*, now, remaining):
    if remaining <= 0:
        return 0

    auctions = Auction.objects.filter(
        extension_notice_dispatched_at__isnull=True,
        end_date__lte=now + timedelta(seconds=1),
    ).order_by('end_date')[:remaining]

    count = 0
    for auction in auctions:
        if auction.get_active_extended_products_count(now) <= 0:
            continue
        try:
            send_auction_extended_notice_sms(auction.id)
            count += 1
        except Exception:
            logger.exception("Dispatch extension notice SMS failed for auction %s", auction.pk)
    return count


def _dispatch_ended(*, now, remaining):
    if remaining <= 0:
        return 0

    auctions = Auction.objects.filter(
        Q(end_notice_dispatched_at__isnull=True) | Q(winner_billing_dispatched_at__isnull=True),
        end_date__lte=now + timedelta(seconds=1),
    ).order_by('end_date')[:remaining]

    count = 0
    for auction in auctions:
        if auction.status == 'extended':
            continue
        try:
            send_auction_ended_email(
                auction.id,
                expected_end=auction.end_date.isoformat(),
            )
            count += 1
        except Exception:
            logger.exception("Dispatch ended email failed for auction %s", auction.pk)
    return count
