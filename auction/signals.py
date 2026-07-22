from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import datetime

from .models import Bid, Auction
from .tasks import (
    send_auction_starting_soon_email,
    send_auction_started_email,
    send_auction_ending_soon_email
)

@receiver(post_save, sender=Auction)
def schedule_auction_emails(sender, instance, created, **kwargs):
    """
    Schedules 3 types of emails based on the auction's start_date and end_date.
    If the auction dates change, new tasks are scheduled (for production, 
    you would usually revoke old tasks, but this uses simple ETA scheduling).
    """
    now = timezone.now()

    # 1. Email: 1 hour before auction starts
    if instance.start_date:
        start_minus_1h = instance.start_date - datetime.timedelta(hours=1)
        if start_minus_1h > now:
            send_auction_starting_soon_email.apply_async((instance.id,), eta=start_minus_1h)

    # 2. Email: Exactly when the auction starts
    if instance.start_date:
        if instance.start_date > now:
            send_auction_started_email.apply_async((instance.id,), eta=instance.start_date)

    # 3. Email: 24 hours before the auction ends
    if instance.end_date:
        end_minus_24h = instance.end_date - datetime.timedelta(hours=24)
        if end_minus_24h > now:
            send_auction_ending_soon_email.apply_async((instance.id,), eta=end_minus_24h)


@receiver(post_save, sender=Bid)
def notify_bid_updates(sender, instance, created, **kwargs):
    if created:
        # 1. Send confirmation email to the user who just placed the bid
        current_user = instance.user
        product_title = getattr(instance.product, 'title', instance.product.product_id)
        
        if current_user.email:
            subject = "ثبت موفق پیشنهاد قیمت"

            message = f"""کاربر گرامی {instance.user_fullname}،

            پیشنهاد قیمت شما به مبلغ {instance.bid_amount:,} تومان برای اثر «{product_title}» با موفقیت در سامانه ثبت شد.

            در صورت ثبت پیشنهادهای جدید توسط سایر شرکت‌کنندگان، از طریق اطلاع‌رسانی‌های سامانه شما را مطلع خواهیم کرد.

            با سپاس از همراهی شما
            تیم ماه آکشن """           
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [current_user.email],
                    fail_silently=True,
                )
            except Exception:
                pass  # Avoid crashing the transaction if email fails

        # 2. Check if there was a previous highest bid on this specific AuctionProduct
        # The new bid is already saved, so we get the highest bid before this one.
        previous_highest_bid = Bid.objects.filter(
            product=instance.product
        ).exclude(id=instance.id).order_by('-bid_amount', '-created_at').first()

        if previous_highest_bid:
            previous_user = previous_highest_bid.user
            # Only send if it's a different user
            if previous_user.id != current_user.id and previous_user.email:
                outbid_subject = "رقابت ادامه دارد؛ پیشنهاد شما دیگر بالاترین قیمت نیست"

                outbid_message = f"""سلام {previous_highest_bid.user_fullname}،

                پیشنهاد قیمت شما برای اثر «{product_title}» دیگر بالاترین پیشنهاد این مزایده نیست.

                بالاترین پیشنهاد فعلی: {instance.bid_amount:,} تومان

                اگر همچنان قصد برنده شدن در این مزایده را دارید، می‌توانید پیشنهاد قیمت جدیدی ثبت کنید.

                با سپاس
                تیم ماه آکشن"""               
                try:
                    send_mail(
                        outbid_subject,
                        outbid_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [previous_user.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
