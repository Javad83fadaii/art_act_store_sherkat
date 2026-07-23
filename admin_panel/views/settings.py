import json
import smtplib
import socket
from email.utils import parseaddr

from django.conf import settings as django_settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import get_connection, send_mail
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.validators import validate_email
from django.views.decorators.http import require_http_methods

from accounts.models import CustomUser
from core.decorators import log_admin_action, superuser_required
from core.models import NotificationPreference, SavedFilter


def _request_payload(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return request.POST.dict()


def _extract_email_address(value):
    _display_name, address = parseaddr((value or '').strip())
    return address.strip()


def _validate_recipient_list(raw_value):
    recipients = []
    invalid_items = []
    normalized_chunks = (
        (raw_value or '')
        .replace('\r', '\n')
        .replace(';', '\n')
        .replace(',', '\n')
        .split('\n')
    )

    for item in normalized_chunks:
        candidate = item.strip()
        if not candidate:
            continue
        candidate = _extract_email_address(candidate)
        if not candidate:
            invalid_items.append(item.strip())
            continue
        try:
            validate_email(candidate)
        except ValidationError:
            invalid_items.append(candidate)
            continue
        recipients.append(candidate)

    if invalid_items:
        raise ValidationError(
            f"این آدرس‌های ایمیل معتبر نیستند: {', '.join(invalid_items)}"
        )

    if not recipients:
        raise ValidationError("حداقل یک آدرس ایمیل معتبر وارد کنید.")

    return list(dict.fromkeys(recipients))


def _selected_user_recipients(user_ids):
    if not user_ids:
        return []

    queryset = (
        CustomUser.objects
        .filter(pk__in=user_ids)
        .exclude(email__isnull=True)
        .exclude(email__exact='')
        .values_list('email', flat=True)
    )
    cleaned_recipients = []
    for email in queryset:
        candidate = (email or '').strip()
        if candidate:
            cleaned_recipients.append(candidate)
    return list(dict.fromkeys(cleaned_recipients))


def _custom_email_user_choices():
    queryset = (
        CustomUser.objects
        .exclude(email__isnull=True)
        .exclude(email__exact='')
        .order_by('-date_joined')
        .values('id', 'full_name', 'email', 'phone_number', 'username')
    )
    users = []
    for item in queryset:
        display_name = (
            (item.get('full_name') or '').strip()
            or (item.get('username') or '').strip()
            or (item.get('phone_number') or '').strip()
            or (item.get('email') or '').strip()
        )
        users.append(
            {
                'id': str(item['id']),
                'name': display_name,
                'email': (item.get('email') or '').strip(),
                'phone_number': (item.get('phone_number') or '').strip(),
            }
        )
    return users


def _email_health_context():
    from_address = getattr(django_settings, 'DEFAULT_FROM_EMAIL', '') or ''
    from_email_address = _extract_email_address(from_address)
    host_user = getattr(django_settings, 'EMAIL_HOST_USER', '') or ''
    backend = getattr(django_settings, 'EMAIL_BACKEND', '') or ''

    issues = []
    if backend == 'django.core.mail.backends.smtp.EmailBackend' and not getattr(django_settings, 'EMAIL_HOST', ''):
        issues.append("مقدار EMAIL_HOST تنظیم نشده است.")
    if backend == 'django.core.mail.backends.smtp.EmailBackend' and not getattr(django_settings, 'EMAIL_PORT', None):
        issues.append("مقدار EMAIL_PORT تنظیم نشده است.")
    if backend == 'django.core.mail.backends.smtp.EmailBackend' and not host_user:
        issues.append("مقدار EMAIL_HOST_USER تنظیم نشده است.")
    if backend == 'django.core.mail.backends.smtp.EmailBackend' and not getattr(django_settings, 'EMAIL_HOST_PASSWORD', ''):
        issues.append("مقدار EMAIL_HOST_PASSWORD تنظیم نشده است.")
    if not from_address:
        issues.append("مقدار DEFAULT_FROM_EMAIL تنظیم نشده است.")
    if getattr(django_settings, 'EMAIL_USE_TLS', False) and getattr(django_settings, 'EMAIL_USE_SSL', False):
        issues.append("EMAIL_USE_TLS و EMAIL_USE_SSL نباید همزمان فعال باشند.")
    if from_email_address and host_user and from_email_address.lower() != host_user.lower():
        issues.append(
            "آدرس داخل DEFAULT_FROM_EMAIL با EMAIL_HOST_USER یکی نبود و می‌توانست باعث بازنویسی یا رد شدن ایمیل شود."
        )

    return {
        'host': getattr(django_settings, 'EMAIL_HOST', ''),
        'port': getattr(django_settings, 'EMAIL_PORT', ''),
        'host_user': host_user,
        'default_from_email': from_address,
        'default_from_address': from_email_address,
        'use_tls': bool(getattr(django_settings, 'EMAIL_USE_TLS', False)),
        'use_ssl': bool(getattr(django_settings, 'EMAIL_USE_SSL', False)),
        'timeout': getattr(django_settings, 'EMAIL_TIMEOUT', ''),
        'backend': getattr(django_settings, 'EMAIL_BACKEND', ''),
        'is_ready': len(issues) == 0,
        'issues': issues,
    }


def _send_email(subject, message, recipients):
    connection = get_connection(fail_silently=False)
    connection.open()
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
            connection=connection,
        )
    finally:
        connection.close()


def _friendly_email_exception(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "احراز هویت SMTP ناموفق بود. EMAIL_HOST_USER یا EMAIL_HOST_PASSWORD "
            "اشتباه است یا سرویس‌دهنده برای این حساب اجازه SMTP نداده است."
        )
    if isinstance(exc, smtplib.SMTPConnectError):
        return "اتصال به سرور SMTP برقرار نشد. EMAIL_HOST، EMAIL_PORT یا دسترسی شبکه را بررسی کنید."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        detail = str(exc).lower()
        if "timed out" in detail:
            return (
                "اتصال به سرور SMTP تایم‌اوت شد. به احتمال زیاد پورت SMTP از این سرور/شبکه "
                "به بیرون باز نیست، فایروال یا هاست آن را بسته است، یا Gmail این اتصال را پاسخ نمی‌دهد."
            )
        return "اتصال سرور SMTP ناگهانی قطع شد. احتمالاً TLS/SSL یا پورت نادرست است."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return (
            "زمان انتظار برای اتصال یا ارسال ایمیل تمام شد. دسترسی شبکه سرور به SMTP، "
            "فایروال، پورت خروجی و EMAIL_TIMEOUT را بررسی کنید."
        )
    return f"ارسال ایمیل با خطا مواجه شد: {exc}"


@superuser_required
def page_view(request):
    email_status = _email_health_context()

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        try:
            if action == 'send_test_email':
                recipient = (request.POST.get('test_recipient') or '').strip()
                if not recipient:
                    recipient = email_status['host_user']
                validate_email(recipient)
                subject = (request.POST.get('test_subject') or 'تست ارسال ایمیل').strip()
                message = (
                    request.POST.get('test_message')
                    or 'این ایمیل برای تست موفق بودن تنظیمات SMTP از داخل پنل مدیریت ارسال شده است.'
                ).strip()
                _send_email(subject, message, [recipient])
                messages.success(request, f"ایمیل تست با موفقیت به {recipient} ارسال شد.")
                return redirect('admin_panel_pages:settings')

            if action == 'send_custom_email':
                recipients = []
                manual_recipients = (request.POST.get('custom_recipients') or '').strip()
                selected_user_ids = [item.strip() for item in request.POST.getlist('selected_user_ids') if item.strip()]

                if manual_recipients:
                    recipients.extend(_validate_recipient_list(manual_recipients))
                recipients.extend(_selected_user_recipients(selected_user_ids))
                recipients = list(dict.fromkeys(recipients))

                if not recipients:
                    raise ValidationError("حداقل یک کاربر یا آدرس ایمیل معتبر انتخاب کنید.")

                subject = (request.POST.get('custom_subject') or '').strip()
                message = (request.POST.get('custom_message') or '').strip()
                if not subject:
                    raise ValidationError("موضوع ایمیل الزامی است.")
                if not message:
                    raise ValidationError("متن ایمیل الزامی است.")
                _send_email(subject, message, recipients)
                messages.success(request, f"ایمیل با موفقیت برای {len(recipients)} گیرنده ارسال شد.")
                return redirect('admin_panel_pages:settings')

            if action:
                messages.error(request, "عملیات انتخاب‌شده معتبر نیست.")
                return redirect('admin_panel_pages:settings')
        except ValidationError as exc:
            error_text = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
            messages.error(request, error_text)
        except Exception as exc:
            messages.error(request, _friendly_email_exception(exc))

    context = {
        'email_status': email_status,
        'settings_data': _settings_payload(),
        'email_users': _custom_email_user_choices(),
    }
    return render(request, 'admin_panel/settings.html', context)


def _settings_payload():
    return {
        'session_cookie_httponly': getattr(django_settings, 'SESSION_COOKIE_HTTPONLY', None),
        'session_cookie_secure': getattr(django_settings, 'SESSION_COOKIE_SECURE', None),
        'session_cookie_samesite': getattr(django_settings, 'SESSION_COOKIE_SAMESITE', None),
        'session_cookie_age': getattr(django_settings, 'SESSION_COOKIE_AGE', None),
        'cache_backend': django_settings.CACHES['default']['BACKEND'],
        'email_backend': getattr(django_settings, 'EMAIL_BACKEND', ''),
        'email_host': getattr(django_settings, 'EMAIL_HOST', ''),
        'email_port': getattr(django_settings, 'EMAIL_PORT', ''),
        'email_use_tls': bool(getattr(django_settings, 'EMAIL_USE_TLS', False)),
        'email_use_ssl': bool(getattr(django_settings, 'EMAIL_USE_SSL', False)),
        'default_from_email': getattr(django_settings, 'DEFAULT_FROM_EMAIL', ''),
        'server_email': getattr(django_settings, 'SERVER_EMAIL', ''),
        'email_timeout': getattr(django_settings, 'EMAIL_TIMEOUT', ''),
    }


@superuser_required
def get_settings(request):
    return JsonResponse(_settings_payload())


@require_http_methods(['GET', 'POST'])
@superuser_required
@log_admin_action('update')
def notifications(request):
    preference, _ = NotificationPreference.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        payload = _request_payload(request)
        if 'email' in payload:
            email_enabled = bool(payload['email'])
            preference.new_user_email = email_enabled
            preference.new_request_email = email_enabled
            preference.new_bid_email = email_enabled
            preference.new_purchase_email = email_enabled
        if 'browser' in payload:
            browser_enabled = bool(payload['browser'])
            preference.new_user_panel = browser_enabled
            preference.new_request_panel = browser_enabled
            preference.new_bid_panel = browser_enabled
            preference.new_purchase_panel = browser_enabled
        preference.save()

    return JsonResponse(
        {
            'email': any(
                [
                    preference.new_user_email,
                    preference.new_request_email,
                    preference.new_bid_email,
                    preference.new_purchase_email,
                ]
            ),
            'browser': any(
                [
                    preference.new_user_panel,
                    preference.new_request_panel,
                    preference.new_bid_panel,
                    preference.new_purchase_panel,
                ]
            ),
        }
    )


@require_http_methods(['GET', 'POST'])
@superuser_required
@log_admin_action('create')
def filters_list(request):
    if request.method == 'POST':
        payload = _request_payload(request)
        page = payload.get('page', '')
        is_default = bool(payload.get('is_default', False))

        if is_default:
            SavedFilter.objects.filter(user=request.user, page=page).update(is_default=False)

        try:
            saved_filter = SavedFilter.objects.create(
                user=request.user,
                name=payload.get('name', ''),
                page=page,
                filters=payload.get('filters', {}),
                is_default=is_default,
            )
        except IntegrityError:
            return JsonResponse({'error': 'فیلتر با این نام قبلا ثبت شده است.'}, status=400)

        return JsonResponse({'id': saved_filter.pk, 'status': 'created'}, status=201)

    filters = list(
        SavedFilter.objects.filter(user=request.user)
        .order_by('-created_at')
        .values('id', 'name', 'page', 'is_default')
    )
    return JsonResponse(
        {
            'filters': [
                {
                    'id': item['id'],
                    'name': item['name'],
                    'filter_type': item['page'],
                    'is_default': item['is_default'],
                }
                for item in filters
            ]
        }
    )


@require_http_methods(['GET', 'PUT', 'DELETE'])
@superuser_required
def filter_detail(request, pk):
    saved_filter = get_object_or_404(SavedFilter, pk=pk, user=request.user)

    if request.method == 'DELETE':
        saved_filter.delete()
        return JsonResponse({'status': 'deleted'})

    if request.method == 'PUT':
        payload = _request_payload(request)
        for field in ('name', 'page', 'filters', 'is_default'):
            if field in payload:
                setattr(saved_filter, field, payload[field])
        saved_filter.save()

    return JsonResponse(
        {
            'id': saved_filter.pk,
            'name': saved_filter.name,
            'page': saved_filter.page,
            'filters': saved_filter.filters,
            'is_default': saved_filter.is_default,
            'created_at': saved_filter.created_at.isoformat(),
        }
    )


@require_http_methods(['POST'])
@superuser_required
@log_admin_action('update')
def set_default_filter(request, pk):
    saved_filter = get_object_or_404(SavedFilter, pk=pk, user=request.user)
    SavedFilter.objects.filter(user=request.user, page=saved_filter.page).update(is_default=False)
    saved_filter.is_default = True
    saved_filter.save(update_fields=['is_default'])
    return JsonResponse({'id': saved_filter.pk, 'is_default': saved_filter.is_default})
