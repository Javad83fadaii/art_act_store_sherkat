import datetime

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.emailing import send_plain_email

from .models import Bid, Auction
from .tasks import (
    send_auction_starting_soon_email,
    send_auction_started_email,
    send_auction_ending_soon_email,
    send_auction_extended_email,
    send_auction_ended_email,
)


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
    if created:
        current_user = instance.user
        product_title = getattr(instance.product, 'title', instance.product.product_id)

        if current_user.email:
            subject = "ثبت موفق پیشنهاد قیمت"

            message = f"""کاربر گرامی {instance.user_fullname}،

پیشنهاد قیمت شما به مبلغ {instance.bid_amount:,} تومان برای اثر «{product_title}» با موفقیت ثبت شد.

تا زمانی که این پیشنهاد بالاترین پیشنهاد فعال باشد، این اثر در سبد خرید مزایده شما نگه داشته می‌شود.

در صورت ثبت پیشنهاد بالاتر توسط کاربر دیگر، هم از طریق سامانه و هم ایمیل شما را مطلع می‌کنیم.

با سپاس از همراهی شما
تیم ماه آکشن"""
            try:
                send_plain_email(
                    subject=subject,
                    message=message,
                    recipients=[current_user.email],
                    fail_silently=True,
                )
            except Exception:
                pass

        previous_highest_bid = Bid.objects.filter(
            product=instance.product
        ).exclude(id=instance.id).order_by('-bid_amount', '-created_at').first()

        if previous_highest_bid:
            previous_user = previous_highest_bid.user
            if previous_user.id != current_user.id and previous_user.email:
                outbid_subject = "رقابت ادامه دارد؛ پیشنهاد شما دیگر بالاترین قیمت نیست"

                outbid_message = f"""سلام {previous_highest_bid.user_fullname}،

پیشنهاد قیمت شما برای اثر «{product_title}» دیگر بالاترین پیشنهاد این مزایده نیست.

بالاترین پیشنهاد فعلی: {instance.bid_amount:,} تومان

به همین دلیل این اثر از سبد خرید مزایده شما خارج شد. در صورت تمایل می‌توانید دوباره پیشنهاد بالاتری ثبت کنید.

با سپاس
تیم ماه آکشن"""
                try:
                    send_plain_email(
                        subject=outbid_subject,
                        message=outbid_message,
                        recipients=[previous_user.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
