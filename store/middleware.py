from django.conf import settings
from django.utils import timezone
from notifications.enums import NotificationProviderType
from notifications.services import send_notification_safely
from .models import SiteVisitLog
from .user_agents import ACCEPT_CH_HEADER, detect_operating_system_from_request, should_replace_operating_system


VERIFICATION_EXEMPT_PATHS = {'/39556468.txt'}
COUNTRY_HEADER_CANDIDATES = (
    'HTTP_CF_IPCOUNTRY',
    'HTTP_CLOUDFRONT_VIEWER_COUNTRY',
    'HTTP_X_COUNTRY_CODE',
    'HTTP_X_COUNTRY',
)
COUNTRY_CODE_LABELS = {
    'IR': 'ایران',
}


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
                self._notify_site_open(request)
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
            self._notify_site_open(request)

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

    def _notify_site_open(self, request):
        if not self._should_send_site_open_alert(request):
            return

        recipients = getattr(settings, 'SITE_VISIT_ALERT_PHONE_NUMBERS', []) or []
        if isinstance(recipients, str):
            recipients = [part.strip() for part in recipients.split(',') if part.strip()]

        if not recipients:
            return

        visitor_name = self._build_visitor_name(request)
        visitor_ip = self.get_client_ip(request) or 'نامشخص'
        visitor_os = detect_operating_system_from_request(request) or 'نامشخص'
        visitor_country = self._resolve_country(request)
        send_notification_safely(
            event='site.visit.alert',
            recipients=recipients,
            providers=[NotificationProviderType.SMS],
            context={
                'VISITOR_NAME': visitor_name,
                'VISITOR_IP': visitor_ip,
                'VISITOR_OS': visitor_os,
                'VISITOR_COUNTRY': visitor_country,
            },
            metadata={
                'sms_pattern': 'site_visit_alert',
                'visitor_name': visitor_name,
                'visitor_ip': visitor_ip,
                'visitor_os': visitor_os,
                'visitor_country': visitor_country,
                'path': request.path,
                'is_authenticated': bool(getattr(request.user, 'is_authenticated', False)),
            },
        )

    def _should_send_site_open_alert(self, request):
        if request.method != 'GET':
            return False

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return False

        accept = str(request.META.get('HTTP_ACCEPT', '') or '').lower()
        return (
            not accept
            or 'text/html' in accept
            or '*/*' in accept
        )

    def _build_visitor_name(self, request):
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            return (
                str(getattr(user, 'full_name', '') or '').strip()
                or str(getattr(user, 'username', '') or '').strip()
                or str(getattr(user, 'phone_number', '') or '').strip()
                or 'کاربر لاگین‌شده'
            )
        return 'مهمان'

    def _resolve_country(self, request):
        for header_name in COUNTRY_HEADER_CANDIDATES:
            raw_value = str(request.META.get(header_name, '') or '').strip()
            if not raw_value:
                continue

            normalized_value = raw_value.upper()
            if normalized_value in {'XX', 'T1'}:
                continue

            if len(normalized_value) == 2 and normalized_value.isalpha():
                return COUNTRY_CODE_LABELS.get(normalized_value, normalized_value)
            return raw_value

        return 'نامشخص'
