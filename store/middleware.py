from django.utils import timezone
from .models import SiteVisitLog
from .user_agents import ACCEPT_CH_HEADER, detect_operating_system_from_request, should_replace_operating_system
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
        # ترکیب User-Agent با Client Hints برای دقت (رفع فریز Android 10 و NT 10.0)
        operating_system = detect_operating_system_from_request(request)
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
                previous_os = visit_log.operating_system or ""
                visit_log.is_closed = True
                visit_log.save(update_fields=['is_closed'])

                # ب) ایجاد یک رکورد جدید برای ادامه حضور کاربر (با همان نشست)
                # اگر مقدار تازه فریز/مبهم است، نسخه دقیق قبلی همین نشست را نگه دار
                new_os = operating_system or ""
                if not should_replace_operating_system(previous_os, new_os) and previous_os:
                    new_os = previous_os
                SiteVisitLog.objects.create(
                    session_key=session_key,
                    ip_address=ip,
                    operating_system=new_os or None,
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

                # هرگز مقدار دقیق (Android 13 / Windows 11) را با مقدار
                # فریز/مبهم (Android 10 / Windows 10/11) برنگردان
                if should_replace_operating_system(visit_log.operating_system, operating_system):
                    visit_log.operating_system = operating_system
                    update_needed = True

                if update_needed:
                    # فقط فیلدهای مورد نیاز را آپدیت کن نه کل مدل را
                    visit_log.save(update_fields=['last_activity', 'user', 'operating_system'])
        
        else:
            # اگر هیچ رکورد بازی برای این نشست وجود نداشت، یکی ایجاد می‌کنیم
            SiteVisitLog.objects.create(
                session_key=session_key,
                ip_address=ip,
                operating_system=operating_system or None,
                user=current_user,
                start_time=now,
                last_activity=now,
                is_closed=False
            )

        response = self.get_response(request)
        # به مرورگر بگو در درخواست‌های بعدی نسخه دقیق OS را بفرستد
        try:
            response["Accept-CH"] = ACCEPT_CH_HEADER
            vary = response.get("Vary", "")
            hints_vary = "Sec-CH-UA-Platform, Sec-CH-UA-Platform-Version"
            if vary:
                if "Sec-CH-UA-Platform" not in vary:
                    response["Vary"] = f"{vary}, {hints_vary}"
            else:
                response["Vary"] = hints_vary
        except Exception:
            pass
        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
