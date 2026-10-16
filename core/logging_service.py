# core/logging_service.py
from decimal import Decimal
import datetime
import uuid

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import AdminActivityLog
from .utils import broadcast_admin_panel_refresh, invalidate_cache


def get_client_ip(request) -> str:
    """دریافت آی‌پی معتبر کاربر از درخواست HTTP."""
    if not request:
        return '127.0.0.1'
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip or '127.0.0.1'


def format_user_display(user) -> str:
    """قالب‌بندی خوانا و استاندارد از مشخصات کاربر برای لاگ."""
    if not user:
        return 'نامشخص'
    full_name = getattr(user, 'full_name', '') or getattr(user, 'get_full_name', lambda: '')() or ''
    phone = getattr(user, 'phone_number', '') or ''
    email = getattr(user, 'email', '') or ''
    username = getattr(user, 'username', '') or ''
    
    parts = []
    if full_name:
        parts.append(str(full_name).strip())
    if phone:
        parts.append(str(phone).strip())
    elif email:
        parts.append(str(email).strip())
    elif username:
        parts.append(str(username).strip())

    return ' - '.join(parts) if parts else str(user)


def _serialize_diff_val(val):
    """تبدیل انواع داده به مقادیر قابل سریالایز در JSON."""
    if val is None:
        return None
    if isinstance(val, (Decimal, uuid.UUID)):
        return str(val)
    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()
    return val


def compute_field_diff(old_data: dict, new_instance, fields_map: dict) -> tuple[dict, list[str]]:
    """
    محاسبه تفاوت فیلدها بین مقادیر قبلی و نمونه جدید.
    fields_map: دیکشنری فیلد به برچسب فارسی آن. e.g. {'is_active': 'وضعیت فعال‌سازی', 'credit': 'اعتبار کل'}
    خروجی: (دیکشنری تغییرات, لیست جملات متنی تغییرات برای استفاده در description)
    """
    changes = {}
    descriptions = []

    for field_name, label in fields_map.items():
        if not hasattr(new_instance, field_name):
            continue
        old_val = old_data.get(field_name)
        new_val = getattr(new_instance, field_name)

        # نرمال‌سازی برای مقایسه Decimal و int و bool
        if isinstance(old_val, Decimal) and isinstance(new_val, (int, float, str, Decimal)):
            try:
                if Decimal(str(old_val)) == Decimal(str(new_val)):
                    continue
            except Exception:
                pass
        elif old_val == new_val:
            continue

        serialized_old = _serialize_diff_val(old_val)
        serialized_new = _serialize_diff_val(new_val)

        changes[field_name] = {
            'label': label,
            'old': serialized_old,
            'new': serialized_new,
        }

        if isinstance(new_val, bool):
            old_text = 'فعال' if old_val else 'غیرفعال'
            new_text = 'فعال' if new_val else 'غیرفعال'
            descriptions.append(f"{label}: از «{old_text}» به «{new_text}»")
        elif field_name in {'credit', 'current_credit', 'starting_price', 'reserve_price', 'price', 'granted_credit'}:
            try:
                old_num = f"{int(Decimal(str(old_val or 0))):,}"
                new_num = f"{int(Decimal(str(new_val or 0))):,}"
                descriptions.append(f"{label}: از {old_num} به {new_num}")
            except Exception:
                descriptions.append(f"{label}: از «{serialized_old}» به «{serialized_new}»")
        else:
            descriptions.append(f"{label}: از «{serialized_old or 'خالی'}» به «{serialized_new or 'خالی'}»")

    return changes, descriptions


def record_admin_activity(
    admin_user,
    action: str,
    description: str = '',
    target_type: str = '',
    target_id: str = '',
    target_repr: str = '',
    changes: dict = None,
    ip_address: str = None,
    request = None,
    content_object = None,
) -> AdminActivityLog:
    """
    ثبت کامل و یکپارچه رویدادهای انجام‌شده توسط مدیران در پنل مدیریت.
    """
    if request:
        if not ip_address:
            ip_address = get_client_ip(request)
        if not admin_user and getattr(request, 'user', None) and request.user.is_authenticated:
            admin_user = request.user

    if not admin_user:
        return None

    ct = None
    obj_id = None
    if content_object:
        try:
            ct = ContentType.objects.get_for_model(content_object)
            raw_pk = getattr(content_object, 'pk', None)
            if isinstance(raw_pk, int):
                obj_id = raw_pk
            if not target_id and raw_pk is not None:
                target_id = str(raw_pk)
            if not target_repr:
                target_repr = str(content_object)
            if not target_type:
                target_type = str(content_object._meta.verbose_name or content_object._meta.model_name)
        except Exception:
            pass

    log_entry = AdminActivityLog.objects.create(
        admin_user=admin_user,
        action=action,
        description=description or '',
        target_type=target_type or '',
        target_id=str(target_id) if target_id else '',
        target_repr=str(target_repr) if target_repr else '',
        content_type=ct,
        object_id=obj_id,
        changes=changes or {},
        ip_address=ip_address or '127.0.0.1',
    )

    # پاکسازی کش لاگ‌ها برای مشاهده بلادرنگ در فرانت‌اند
    try:
        invalidate_cache('admin_report_activity_logs*')
        invalidate_cache('admin_report_admin_logs*')
        invalidate_cache('admin_dashboard_activities*')
    except Exception:
        pass

    # ارسال نوتیفیکیشن بلادرنگ به پنل
    try:
        transaction.on_commit(
            lambda: broadcast_admin_panel_refresh(
                actor=admin_user,
                action_type=action,
                path=getattr(request, 'path', '') if request else '',
                object_id=target_id or 0,
            )
        )
    except Exception:
        pass

    return log_entry
