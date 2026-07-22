try:
    from celery import shared_task
except ImportError:
    def shared_task(func):
        func.delay = func

        def _apply_async(args=None, kwargs=None, eta=None, **options):
            call_args = tuple(args or ())
            call_kwargs = dict(kwargs or {})
            return func(*call_args, **call_kwargs)

        func.apply_async = _apply_async
        return func
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import Auction

CustomUser = get_user_model()

def get_active_users_emails():
    # Only get emails of verified/active users who have an email set
    users = CustomUser.objects.filter(is_active=True).exclude(email__isnull=True).exclude(email__exact='')
    return list(users.values_list('email', flat=True))


@shared_task
def send_auction_starting_soon_email(auction_id):
    """Sent 1 hour before auction starts."""
    try:
        auction = Auction.objects.get(id=auction_id)
        emails = get_active_users_emails()
        
        if emails:
            subject = f"مزایده «{auction.name}» تا ۱ ساعت دیگر آغاز می‌شود"

            message = f"""سلام،

            این یک یادآوری است که مزایده «{auction.name}» دقیقاً تا ۱ ساعت دیگر آغاز خواهد شد.

            برای شرکت در مزایده و ثبت پیشنهاد قیمت، لطفاً در زمان مقرر وارد سامانه شوید.

            با آرزوی موفقیت
            تیم ماه آکشن
            """            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                emails,
                fail_silently=True,
            )
    except Auction.DoesNotExist:
        pass


@shared_task
def send_auction_started_email(auction_id):
    """Sent exactly when auction starts."""
    try:
        auction = Auction.objects.get(id=auction_id)
        emails = get_active_users_emails()
        
        if emails:
            subject = f"زمان رقابت فرا رسید؛ مزایده «{auction.name}» آغاز شد"

            message = f"""سلام،

            مزایده «{auction.name}» هم‌اکنون آغاز شده است.

            فرصت شرکت در رقابت و ثبت پیشنهاد قیمت برای آثار این مزایده از همین لحظه فراهم است.

            همین حالا وارد سامانه شوید و شانس خود را برای برنده شدن امتحان کنید.

            با آرزوی موفقیت
            تیم ماه آکشن"""         
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                emails,
                fail_silently=True,
            )
    except Auction.DoesNotExist:
        pass


@shared_task
def send_auction_ending_soon_email(auction_id):
    """Sent 24 hours before auction ends."""
    try:
        auction = Auction.objects.get(id=auction_id)
        emails = get_active_users_emails()
        
        if emails:
            subject = f"یادآوری: ۲۴ ساعت تا پایان مزایده «{auction.name}»"

            message = f"""سلام،

            مزایده «{auction.name}» تنها تا ۲۴ ساعت دیگر به پایان خواهد رسید.

            این آخرین فرصت برای بررسی وضعیت پیشنهادهای شما و ثبت پیشنهاد جدید جهت افزایش شانس برنده شدن است.

            همین حالا وارد سامانه شوید و از آخرین وضعیت مزایده مطلع شوید.

            با سپاس
            تیم ماه آکشن"""         
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                emails,
                fail_silently=True,
            )
    except Auction.DoesNotExist:
        pass
