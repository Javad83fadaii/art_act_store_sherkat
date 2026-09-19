from django.utils import timezone
from .models import SiteVisitLog
import datetime


VERIFICATION_EXEMPT_PATHS = {'/39556468.txt'}


class VisitTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ۱. نادیده گرفتن درخواست‌های مربوط به فایل‌های استاتیک و ادمین (برای کاهش فشار دیتابیس)
        if (
            request.path.startswith('/static/')
            or request.path.startswith('/media/')
            or request.path.startswith('/admin/')
            or request.path in VERIFICATION_EXEMPT_PATHS
        ):
            return self.get_response(request)

        # ۲. اطمینان از وجود سشن (برای کاربران مهمان)
        if not request.session.session_key:
            request.session.create()
        
        session_key = request.session.session_key

        # ۳. دریافت IP کاربر به صورت بهینه
        ip = self.get_client_ip(request)
        current_user = request.user if request.user.is_authenticated else None
        now = timezone.now()

        # ۴. دریافت آخرین لاگ حضور باز (پایان نیافته) برای این نشست
        visit_log = SiteVisitLog.objects.filter(
            session_key=session_key, 
            is_closed=False
        ).order_by('-last_activity').first()

        if visit_log:
            # محاسبه اختلاف زمان (به ثانیه) بین الان و آخرین فعالیت ثبت شده
            delta_seconds = (now - visit_log.last_activity).total_seconds()

            # ۵. بررسی آستانه عدم فعالیت (۱۰ دقیقه = ۶۰۰ ثانیه)
            if delta_seconds > 600:
                # الف) بستن رکورد قبلی
                visit_log.is_closed = True
                visit_log.save(update_fields=['is_closed'])

                # ب) ایجاد یک رکورد جدید برای ادامه حضور کاربر (با همان نشست)
                SiteVisitLog.objects.create(
                    session_key=session_key,
                    ip_address=ip,
                    user=current_user,
                    start_time=now,
                    last_activity=now,
                    is_closed=False
                )
            else:
                # ۶. بهینه‌سازی: فقط در صورتی دیتابیس را آپدیت کن که بیش از ۶۰ ثانیه از آخرین فعالیت گذشته باشد
                update_needed = False
                
                # اگر بیش از ۶۰ ثانیه گذشته باشد
                if delta_seconds > 60:
                    visit_log.last_activity = now
                    update_needed = True
                
                # اگر کاربر وسط نشست لاگین کرد، آیدی او را همان لحظه ثبت کن
                if current_user and not visit_log.user:
                    visit_log.user = current_user
                    update_needed = True

                if update_needed:
                    # فقط فیلدهای مورد نیاز را آپدیت کن نه کل مدل را
                    visit_log.save(update_fields=['last_activity', 'user'])
        
        else:
            # اگر هیچ رکورد بازی برای این نشست وجود نداشت، یکی ایجاد می‌کنیم
            SiteVisitLog.objects.create(
                session_key=session_key,
                ip_address=ip,
                user=current_user,
                start_time=now,
                last_activity=now,
                is_closed=False
            )

        response = self.get_response(request)
        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
