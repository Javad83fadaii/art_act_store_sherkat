import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Auction
from .tasks import (
    send_auction_ended_email,
    send_auction_ending_soon_email,
    send_auction_started_email,
    send_auction_starting_soon_email,
)


logger = logging.getLogger(__name__)


def dispatch_due_auction_emails(*, limit=10):
    now = timezone.now()
    dispatched = 0

    dispatched += _dispatch_starting_soon(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_started(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_ending_soon(now=now, remaining=max(limit - dispatched, 0))
    dispatched += _dispatch_ended(now=now, remaining=max(limit - dispatched, 0))

    return dispatched


def _dispatch_starting_soon(*, now, remaining):
    if remaining <= 0:
        return 0

    lower_bound = now + timedelta(hours=23, minutes=55)
    upper_bound = now + timedelta(hours=24, seconds=1)
    auctions = Auction.objects.filter(
        start_reminder_24h_dispatched_at__isnull=True,
        start_date__gte=lower_bound,
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

    lower_bound = now - timedelta(minutes=5)
    upper_bound = now + timedelta(seconds=1)
    auctions = Auction.objects.filter(
        start_notice_dispatched_at__isnull=True,
        start_date__gte=lower_bound,
        start_date__lte=upper_bound,
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


def _dispatch_ending_soon(*, now, remaining):
    if remaining <= 0:
        return 0

    lower_bound = now + timedelta(hours=11, minutes=55)
    upper_bound = now + timedelta(hours=12, seconds=1)
    auctions = Auction.objects.filter(
        end_reminder_12h_dispatched_at__isnull=True,
        end_date__gte=lower_bound,
        end_date__lte=upper_bound,
    ).order_by('end_date')[:remaining]

    count = 0
    for auction in auctions:
        try:
            send_auction_ending_soon_email(
                auction.id,
                expected_end=auction.end_date.isoformat(),
            )
            count += 1
        except Exception:
            logger.exception("Dispatch ending-soon email failed for auction %s", auction.pk)
    return count


def _dispatch_ended(*, now, remaining):
    if remaining <= 0:
        return 0

    lower_bound = now - timedelta(minutes=5)
    auctions = Auction.objects.filter(
        Q(end_notice_dispatched_at__isnull=True) | Q(winner_billing_dispatched_at__isnull=True),
        end_date__gte=lower_bound,
        end_date__lte=now + timedelta(seconds=1),
    ).order_by('end_date')[:remaining]

    count = 0
    for auction in auctions:
        try:
            send_auction_ended_email(
                auction.id,
                expected_end=auction.end_date.isoformat(),
            )
            count += 1
        except Exception:
            logger.exception("Dispatch ended email failed for auction %s", auction.pk)
    return count
