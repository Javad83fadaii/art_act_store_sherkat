import json
from decimal import Decimal
from datetime import datetime

from django.core.paginator import Paginator
from django.db.models import Count, Q, Max, Subquery, OuterRef, IntegerField, DateTimeField
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.realtime import build_profile_live_context
from accounts.forms import AdminUserEditForm
from accounts.models import VerificationRequest
from accounts.models import CustomUser
from core.models import SavedFilter
from auction.models import AuctionCartItem, AuctionVisitHistory, Bid
from core.decorators import log_admin_action, staff_required, superuser_required
from core.models import ActivityLog
from core.utils import cache_response, invalidate_cache
from store.models import SiteVisitLog, VisitHistory, PurchaseHistory, TelegramPurchaseRequest
# در صورتی که AuctionVisit در فایل دیگری است، ایمپورت آن را متناسب با پروژه تنظیم کنید
# from auction.models import AuctionVisit

AUTH_ACTIVITY_ACTIONS = ['Login', 'Logout', 'Login Failed']


def _request_payload(request):
    """
    تابع کمکی برای دریافت و پارس کردن امن داده‌های ارسالی کاربر.
    """
    try:
        return json.loads(request.body.decode() or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return request.POST.dict()


def _serialize_user_detail(user):
    profile_picture_url = ""
    if getattr(user, "profile_picture", None):
        try:
            profile_picture_url = user.profile_picture.url
        except ValueError:
            profile_picture_url = ""

    current_credit = user.calculate_current_credit()

    return {
        "id": str(user.pk),
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "full_name": user.full_name or "",
        "name": user.get_full_name() or user.email or user.phone_number,
        "phone_number": user.phone_number or "",
        "email": user.email or "",
        "telegram_id": user.telegram_id or "",
        "preferred_contact_methods": user.preferred_contact_methods or [],
        "newsletter_catalog_opt_in": bool(getattr(user, "newsletter_catalog_opt_in", False)),
        "address_country": user.address_country or "",
        "address_city": user.address_city or "",
        "address_street": user.address_street or "",
        "description": user.description or "",
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_verified": int(user.is_verified or 0),
        "credit": str(user.credit or 0),
        "current_credit": str(current_credit),
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "profile_picture_url": profile_picture_url,
        "profile_picture_name": user.profile_picture.name if getattr(user, "profile_picture", None) else "",
    }


def _safe_iso(value):
    return value.isoformat() if value else None


def _short_session_key(session_key):
    if not session_key:
        return 'نامشخص'
    if len(session_key) <= 10:
        return session_key
    return f'{session_key[:8]}...'


def _build_auth_activity_entry(activity):
    action = activity.action or ''
    action_map = {
        'Login': ('ورود به سیستم', 'success', 'موفق'),
        'Logout': ('خروج از سیستم', 'warning', 'پایان نشست'),
        'Login Failed': ('ورود ناموفق', 'danger', 'ناموفق'),
    }
    event_label, status, status_label = action_map.get(
        action,
        (action or 'رویداد نامشخص', 'neutral', 'نامشخص'),
    )
    return {
        'source': 'auth',
        'source_label': 'ورود و خروج',
        'event_type': action or 'Unknown',
        'event_label': event_label,
        'status': status,
        'status_label': status_label,
        'details': activity.details or '',
        'occurred_at': _safe_iso(activity.timestamp),
        '_sort_at': activity.timestamp,
    }


def _build_site_visit_entry(log):
    duration_min = getattr(log, 'duration_in_minutes', 0)
    is_closed = bool(getattr(log, 'is_closed', False))
    return {
        'source': 'visit',
        'source_label': 'حضور در سایت',
        'event_type': 'Site Visit',
        'event_label': 'نشست کاربر در سایت',
        'status': 'closed' if is_closed else 'active',
        'status_label': 'پایان یافته' if is_closed else 'فعال',
        'details': f"IP: {log.ip_address or 'نامشخص'}",
        'occurred_at': _safe_iso(log.last_activity),
        '_sort_at': log.last_activity,
        'ip': log.ip_address or 'نامشخص',
        'start_time': _safe_iso(log.start_time),
        'last_activity': _safe_iso(log.last_activity),
        'duration_min': duration_min,
        'session_key': log.session_key or '',
        'session_key_short': _short_session_key(log.session_key),
        'is_closed': is_closed,
    }


def _serialize_timeline_page(entries, page_number, page_size):
    paginator = Paginator(entries, page_size)
    page_obj = paginator.get_page(page_number)
    serialized_entries = []

    for item in page_obj.object_list:
        serialized = dict(item)
        serialized.pop('_sort_at', None)
        serialized_entries.append(serialized)

    return paginator, page_obj, serialized_entries


def _get_auction_request_status(user):
    if int(getattr(user, 'is_verified', 0) or 0) == 1:
        return 'approved'

    statuses = set(
        user.verification_requests.values_list('status', flat=True)
    )

    if VerificationRequest.RequestStatus.PENDING in statuses:
        return 'pending'
    return ''


def _store_status_payload(artwork, telegram_status=None):
    if artwork:
        if artwork.is_sold == 2:
            return 'reserved', 'در حال رزرو'
        if artwork.is_sold == 1:
            return 'purchased', 'خریداری شده'

    status_map = {
        'pending': ('reserved', 'در حال رزرو'),
        'confirmed': ('purchased', 'خریداری شده'),
        'contacted': ('purchased', 'خریداری شده'),
        'rejected': ('rejected', 'لغو شده'),
    }
    return status_map.get(telegram_status, ('unknown', 'نامشخص'))


@staff_required
def page_view(request):
    """
    رندر کردن قالب HTML اصلی صفحه مدیریت کاربران (لیست کاربران).
    """
    return render(request, 'admin_panel/users.html')


@staff_required
def history_page_view(request, pk):
    """
    رندر کردن قالب HTML صفحه تاریخچه کاربر (حضور در سایت و ورود/خروج).
    """
    user = get_object_or_404(CustomUser, pk=pk)
    context = {
        'user_id': pk,
        'user_name': user.get_full_name() or user.email,
        'user': user,
    }
    return render(request, 'admin_panel/user_history.html', context)


@superuser_required
def login_history_page_view(request):
    return render(request, 'admin_panel/user_activity_history.html', {'initial_source': 'all'})


@staff_required
@require_http_methods(['GET'])
def history_api_view(request, pk):
    """
    API دریافت تاریخچه ورود و خروج، و حضور کاربر در سایت.
    """
    user = get_object_or_404(CustomUser, pk=pk)
    try:
        activity_page = max(1, int(request.GET.get('page', request.GET.get('activity_page', 1))))
    except (ValueError, TypeError):
        activity_page = 1

    page_size = 12

    auth_activities = list(
        ActivityLog.objects
        .filter(user=user, action__in=AUTH_ACTIVITY_ACTIONS)
        .order_by('-timestamp')
    )
    visit_logs = list(
        SiteVisitLog.objects
        .filter(user=user)
        .order_by('-last_activity')
    )

    login_logout_history = [
        {
            'timestamp': _safe_iso(activity.timestamp),
            'action': activity.action,
            'details': activity.details or '',
            'event_label': _build_auth_activity_entry(activity)['event_label'],
            'status': _build_auth_activity_entry(activity)['status'],
            'status_label': _build_auth_activity_entry(activity)['status_label'],
        }
        for activity in auth_activities
    ]

    site_visit_history = [
        {
            'session_key': log.session_key,
            'session_key_short': _short_session_key(log.session_key),
            'ip': log.ip_address or 'نامشخص',
            'start_time': _safe_iso(log.start_time),
            'last_activity': _safe_iso(log.last_activity),
            'duration_min': getattr(log, 'duration_in_minutes', 0),
            'is_closed': bool(getattr(log, 'is_closed', False)),
        }
        for log in visit_logs
    ]

    activity_entries = [
        *[_build_auth_activity_entry(activity) for activity in auth_activities],
        *[_build_site_visit_entry(log) for log in visit_logs],
    ]
    activity_entries.sort(key=lambda item: item.get('_sort_at') or datetime.min, reverse=True)
    activity_paginator, activity_page_obj, activity_timeline = _serialize_timeline_page(
        activity_entries,
        activity_page,
        page_size,
    )

    login_count = sum(1 for item in auth_activities if item.action == 'Login')
    logout_count = sum(1 for item in auth_activities if item.action == 'Logout')
    failed_login_count = sum(1 for item in auth_activities if item.action == 'Login Failed')
    active_site_sessions = sum(1 for item in visit_logs if not getattr(item, 'is_closed', False))

    return JsonResponse({
        'user_id': str(user.id),
        'login_logout_history': login_logout_history,
        'site_visit_history': site_visit_history,
        'visit_total_count': len(site_visit_history),
        'visit_page': activity_page_obj.number,
        'visit_page_count': activity_paginator.num_pages,
        'page_size': page_size,
        'activity_timeline': activity_timeline,
        'activity_total_count': len(activity_entries),
        'activity_page': activity_page_obj.number,
        'activity_page_count': activity_paginator.num_pages,
        'summary': {
            'site_visit_count': len(site_visit_history),
            'auth_event_count': len(login_logout_history),
            'login_count': login_count,
            'logout_count': logout_count,
            'failed_login_count': failed_login_count,
            'active_site_sessions': active_site_sessions,
        },
    })


@superuser_required
@require_http_methods(['GET'])
def login_history_api_view(request):
    auth_queryset = ActivityLog.objects.select_related('user').order_by('-timestamp')
    visit_queryset = SiteVisitLog.objects.select_related('user').order_by('-last_activity')

    user_id = request.GET.get('user_id', '').strip()
    if user_id:
        auth_queryset = auth_queryset.filter(user_id=user_id)
        visit_queryset = visit_queryset.filter(user_id=user_id)

    guest_ip = request.GET.get('guest_ip', '').strip()
    if guest_ip:
        auth_queryset = auth_queryset.none()
        visit_queryset = visit_queryset.filter(user__isnull=True, ip_address__iexact=guest_ip)

    search = request.GET.get('search', '').strip()
    if search:
        auth_queryset = auth_queryset.filter(
            Q(action__icontains=search)
            | Q(details__icontains=search)
            | Q(user__email__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__phone_number__icontains=search)
        )
        visit_queryset = visit_queryset.filter(
            Q(ip_address__icontains=search)
            | Q(session_key__icontains=search)
            | Q(user__email__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__phone_number__icontains=search)
        )

    action = request.GET.get('action', '').strip()
    if action:
        auth_queryset = auth_queryset.filter(action__iexact=action)

    source = request.GET.get('source', 'all').strip() or 'all'
    if source not in {'all', 'auth', 'visit'}:
        source = 'all'

    auth_payload = []
    if source in {'all', 'auth'}:
        for item in auth_queryset:
            entry = _build_auth_activity_entry(item)
            auth_payload.append(
                {
                    'id': item.id,
                    'user_name': (item.user.get_full_name() or item.user.email or item.user.phone_number) if item.user else 'کاربر ناشناس',
                    'user_id': str(item.user_id) if item.user_id else None,
                    'source': entry['source'],
                    'source_label': entry['source_label'],
                    'action': item.action,
                    'event_label': entry['event_label'],
                    'details': item.details or '',
                    'status': entry['status'],
                    'status_label': entry['status_label'],
                    'timestamp': _safe_iso(item.timestamp),
                    '_sort_at': item.timestamp,
                }
            )

    visit_payload = []
    if source in {'all', 'visit'}:
        for log in visit_queryset:
            entry = _build_site_visit_entry(log)
            user_display = 'مهمان (ناشناس)'
            user_id = None
            if log.user:
                user_display = log.user.get_full_name() or log.user.email or log.user.phone_number
                user_id = str(log.user_id)
            visit_payload.append(
                {
                    'id': f'visit-{log.id}',
                    'user_name': user_display,
                    'user_id': user_id,
                    'source': entry['source'],
                    'source_label': entry['source_label'],
                    'action': entry['event_type'],
                    'event_label': entry['event_label'],
                    'details': entry['details'],
                    'status': entry['status'],
                    'status_label': entry['status_label'],
                    'timestamp': entry['occurred_at'],
                    'ip_address': entry['ip'],
                    'duration_min': entry['duration_min'],
                    'session_key_short': entry['session_key_short'],
                    '_sort_at': log.last_activity,
                }
            )

    combined_payload = [*auth_payload, *visit_payload]
    combined_payload.sort(key=lambda item: item.get('_sort_at') or datetime.min, reverse=True)

    paginator = Paginator(combined_payload, 100)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    payload = []
    for item in page_obj.object_list:
        entry = dict(item)
        entry.pop('_sort_at', None)
        payload.append(entry)

    return JsonResponse(
        {
            'results': payload,
            'total': paginator.count,
            'pages': paginator.num_pages,
            'current_page': page_obj.number,
            'source': source,
            'auth_total': len(auth_payload),
            'visit_total': len(visit_payload),
            'active_user_id': user_id or None,
            'active_guest_ip': guest_ip or None,
        }
    )


@staff_required
@cache_response(timeout=180, key_prefix='admin_users')
def list_view(request):
    """
    دریافت لیست کاربران به همراه فیلتر وضعیت، جستجوی پیشرفته و صفحه‌بندی.
    امکان نمایش تمام کاربران با ارسال پارامتر show_all=true در URL فراهم شده است.
    """
    activity_subquery = (
        ActivityLog.objects
        .filter(user_id=OuterRef('pk'))
        .order_by('-timestamp')
        .values('timestamp')[:1]
    )
    store_visits_subquery = (
        VisitHistory.objects
        .filter(user_id=OuterRef('pk'))
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    auction_visits_subquery = (
        AuctionVisitHistory.objects
        .filter(user_id=OuterRef('pk'), product__isnull=True)
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    auction_product_visits_subquery = (
        AuctionVisitHistory.objects
        .filter(user_id=OuterRef('pk'), product__isnull=False)
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    site_sessions_subquery = (
        SiteVisitLog.objects
        .filter(user_id=OuterRef('pk'))
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    active_site_sessions_subquery = (
        SiteVisitLog.objects
        .filter(user_id=OuterRef('pk'), is_closed=False)
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    auth_activity_count_subquery = (
        ActivityLog.objects
        .filter(user_id=OuterRef('pk'), action__in=AUTH_ACTIVITY_ACTIONS)
        .values('user_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    users = (
        CustomUser.objects
        .all()
        .prefetch_related('verification_requests')
        .annotate(
            last_activity_time=Subquery(activity_subquery, output_field=DateTimeField()),
            store_visits_count=Coalesce(Subquery(store_visits_subquery, output_field=IntegerField()), 0),
            auction_visits_count=Coalesce(Subquery(auction_visits_subquery, output_field=IntegerField()), 0),
            auction_product_visits_count=Coalesce(
                Subquery(auction_product_visits_subquery, output_field=IntegerField()),
                0,
            ),
            site_sessions_count=Coalesce(Subquery(site_sessions_subquery, output_field=IntegerField()), 0),
            active_site_sessions_count=Coalesce(
                Subquery(active_site_sessions_subquery, output_field=IntegerField()),
                0,
            ),
            auth_activity_count=Coalesce(Subquery(auth_activity_count_subquery, output_field=IntegerField()), 0),
        )
    )

    has_manual_filters = any([
        request.GET.get('status'),
        request.GET.get('search'),
        request.GET.get('date_joined__gte'),
        request.GET.get('date_joined__lte'),
        request.GET.get('is_staff'),
    ])

    if not has_manual_filters:
        default_filter = SavedFilter.objects.filter(page='users', is_default=True).first()
        if default_filter and default_filter.criteria:
            filter_kwargs = {}
            for key, value in default_filter.criteria.items():
                if key == 'status':
                    if value == 'active':
                        filter_kwargs['is_active'] = True
                    elif value == 'inactive':
                        filter_kwargs['is_active'] = False
                    continue
                if '__gte' in key or '__lte' in key or 'date_joined' in key:
                    try:
                        if isinstance(value, str):
                            value = datetime.fromisoformat(value).date()
                    except (ValueError, AttributeError):
                        pass
                filter_kwargs[key] = value
            
            if filter_kwargs:
                users = users.filter(**filter_kwargs)
    else:
        status = request.GET.get('status')
        if status:
            if status == 'active':
                users = users.filter(is_active=True)
            elif status == 'inactive':
                users = users.filter(is_active=False)

        search = request.GET.get('search')
        if search:
            users = users.filter(CustomUser.search_q(search))

    # مرتب‌سازی پایه
    sort_param = request.GET.get('sort', '-date_joined')
    if sort_param:
        sort_fields = [s.strip() for s in sort_param.split(',') if s.strip()]
        if sort_fields:
            users = users.order_by(*sort_fields)
        else:
            users = users.order_by('-date_joined')
    else:
        users = users.order_by('-date_joined')

    # تعیین سایز صفحه‌بندی (100 عدد پیش‌فرض یا نمایش همه)
    show_all = request.GET.get('show_all') == 'true'
    total_users_count = users.count()
    
    if show_all and total_users_count > 0:
        page_size = total_users_count
    else:
        page_size = 100

    # صفحه‌بندی قبل از انجام محاسبات
    paginator = Paginator(users, page_size)
    page = paginator.get_page(request.GET.get('page', 1))
    
    payload = []
    for user in page.object_list:
        payload.append({
            'id': user.id,
            'phone_number': user.phone_number,
            'name': user.get_full_name() or user.email,
            'username': user.username or '',
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'is_verified': int(user.is_verified or 0),
            'email': user.email or '',
            'telegram_id': user.telegram_id or '',
            'newsletter_catalog_opt_in': bool(getattr(user, 'newsletter_catalog_opt_in', False)),
            'address_city': user.address_city or '',
            'address_country': user.address_country or '',
            'credit': str(user.credit or 0),
            'current_credit': str(user.current_credit or 0),
            'last_login': _safe_iso(user.last_login),
            'auction_request_status': _get_auction_request_status(user),
            'date_joined': user.date_joined.isoformat() if user.date_joined else None,
            'store_visits_count': int(getattr(user, 'store_visits_count', 0) or 0),
            'auction_visits_count': int(getattr(user, 'auction_visits_count', 0) or 0),
            'auction_product_visits_count': int(getattr(user, 'auction_product_visits_count', 0) or 0),
            'site_sessions_count': int(getattr(user, 'site_sessions_count', 0) or 0),
            'active_site_sessions_count': int(getattr(user, 'active_site_sessions_count', 0) or 0),
            'auth_activity_count': int(getattr(user, 'auth_activity_count', 0) or 0),
            'last_activity': user.last_activity_time.isoformat() if user.last_activity_time else None,
        })

    return JsonResponse(
        {
            'users': payload,
            'total': paginator.count,
            'pages': paginator.num_pages,
            'current_page': page.number,
            'page_size': page_size,
        }
    )


@require_http_methods(['GET', 'PUT', 'POST'])
@staff_required
@log_admin_action('update')
def detail_view(request, pk):
    """
    دریافت (GET) و به‌روزرسانی (PUT/POST) اطلاعات یک کاربر خاص.
    """
    user = get_object_or_404(CustomUser, pk=pk)

    if request.method in ['PUT', 'POST']:
        if request.content_type and 'application/json' in request.content_type:
            data = _request_payload(request)
            form = AdminUserEditForm(data=data, files=request.FILES or None, instance=user)
        else:
            form = AdminUserEditForm(data=request.POST, files=request.FILES, instance=user)

        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()}, status=400)

        user = form.save()
        invalidate_cache('admin_users*')

        return JsonResponse({'success': True, 'user': _serialize_user_detail(user)})

    # درخواست حالت GET (باز شدن اولیه پنل)
    return JsonResponse(_serialize_user_detail(user))


@require_http_methods(['POST'])
@staff_required
@log_admin_action('update')
def bulk_action(request):
    """
    انجام عملیات گروهی روی چند کاربر (مانند فعال/غیرفعال سازی دسته‌جمعی).
    """
    data = _request_payload(request)
    ids = data.get('ids', [])
    action = data.get('action')

    if not ids or not action:
        return JsonResponse({'error': 'Invalid payload'}, status=400)

    queryset = CustomUser.objects.filter(pk__in=ids)

    if action == 'activate':
        queryset.update(is_active=True)
    elif action == 'deactivate':
        queryset.update(is_active=False)
    else:
        return JsonResponse({'error': 'Unknown action'}, status=400)

    invalidate_cache('admin_users*')
    return JsonResponse({'success': True})


@staff_required
@cache_response(timeout=180, key_prefix='admin_user_auction_activity')
def auction_activity(request, pk):
    """
    دریافت آمار فعالیت‌های کاربر در مزایده‌ها با استفاده از کوئری‌های بهینه‌شده دیتابیس.
    """
    user = get_object_or_404(CustomUser, pk=pk)

    bids = (
        Bid.objects.filter(user=user)
        .select_related('auction', 'auction__artwork')
        .values('auction_id', 'auction__artwork__title')
        .annotate(total_bids=Count('id'))
        .order_by('-total_bids')
    )

    payload = [
        {
            'auction_id': item['auction_id'],
            'artwork_title': item['auction__artwork__title'],
            'total_bids': item['total_bids'],
        }
        for item in bids
    ]

    return JsonResponse({'user_id': user.id, 'bids': payload})


# ─────────────────────────────────────────────────────────────────────────────
# ── بخش جدید: تاریخچه کل حضور در سایت (Global Site Visits) ───────────────────
# ─────────────────────────────────────────────────────────────────────────────

@superuser_required
@require_http_methods(['GET'])
def global_site_visits_page_view(request):
    """
    رندر کردن قالب HTML اختصاصی برای صفحه تاریخچه کل حضور تمامی کاربران و مهمان‌ها در سایت.
    """
    return render(request, 'admin_panel/user_activity_history.html', {'initial_source': 'visit'})


@superuser_required
@require_http_methods(['GET'])
def global_site_visits_api_view(request):
    """
    API واکشی لاگ‌های کل حضور در سایت.
    شامل جستجوی پیشرفته، فیلتر وضعیت و صفحه‌بندی برای رندر در DataTable سفارشی.
    """
    # واکشی رکوردها به همراه اطلاعات کاربر برای جلوگیری از N+1 Query
    queryset = SiteVisitLog.objects.select_related('user').all().order_by('-last_activity')

    # جستجوی ترکیبی روی آی‌پی و مشخصات کاربر
    search_query = request.GET.get('search', '').strip()
    if search_query:
        queryset = queryset.filter(
            Q(ip_address__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query)
        )

    # فیلتر وضعیت فعال یا بسته شده
    status_filter = request.GET.get('status')
    if status_filter == 'closed':
        queryset = queryset.filter(is_closed=True)
    elif status_filter == 'active':
        queryset = queryset.filter(is_closed=False)

    # صفحه‌بندی بهینه
    items_per_page = 20
    paginator = Paginator(queryset, items_per_page)
    page_number = request.GET.get('page', 1)
    
    try:
        page_obj = paginator.get_page(page_number)
    except Exception:
        page_obj = paginator.get_page(1)

    payload = []
    for log in page_obj.object_list:
        user_display = "مهمان (ناشناس)"
        user_id = None
        
        if log.user:
            user_display = log.user.get_full_name() or log.user.email
            user_id = log.user.id

        safe_session_key = log.session_key[:8] + '...' if log.session_key else 'نامشخص'

        # محاسبه مدت زمان (در صورتی که متد آن در مدل وجود نداشته باشد، محاسبه دستی انجام می‌شود)
        try:
            duration = log.duration_in_minutes
        except AttributeError:
            if log.last_activity and log.start_time:
                time_difference = log.last_activity - log.start_time
                duration = int(time_difference.total_seconds() / 60)
            else:
                duration = 0

        payload.append({
            'id': log.id,
            'session_key': safe_session_key,
            'user_display': user_display,
            'user_id': user_id,
            'ip_address': log.ip_address or 'نامشخص',
            'start_time': log.start_time.isoformat() if log.start_time else None,
            'last_activity': log.last_activity.isoformat() if log.last_activity else None,
            'duration_minutes': duration,
            'is_closed': log.is_closed,
        })

    return JsonResponse({
        'logs': payload,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    }, status=200)

# ─────────────────────────────────────────────────────────────────────────────
# ── API جدید: تاریخچه بازدید محصولات برای یک کاربر خاص ──────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@staff_required
@require_http_methods(['GET'])
def user_product_visits_api(request, pk):
    """
    API دریافت تاریخچه بازدیدهای کاربر در سه دسته:
    محصولات فروشگاه، محصولات مزایده و خود مزایده‌ها.
    """
    user = get_object_or_404(CustomUser, pk=pk)

    visit_type = request.GET.get('type', 'store_products').strip()
    valid_types = {'store_products', 'auction_products', 'auctions'}
    if visit_type not in valid_types:
        visit_type = 'store_products'

    store_base_queryset = VisitHistory.objects.filter(user=user)
    auction_product_base_queryset = AuctionVisitHistory.objects.filter(user=user).exclude(product_id__isnull=True)
    auction_base_queryset = AuctionVisitHistory.objects.filter(user=user, product_id__isnull=True)

    store_summary = {
        'total_items': store_base_queryset.values('product_id').distinct().count(),
        'total_visits': store_base_queryset.count(),
    }
    auction_product_summary = {
        'total_items': auction_product_base_queryset.values('product_id').distinct().count(),
        'total_visits': auction_product_base_queryset.count(),
    }
    auction_summary = {
        'total_items': auction_base_queryset.values('auction_id').distinct().count(),
        'total_visits': auction_base_queryset.count(),
    }

    if visit_type == 'auction_products':
        queryset = (
            auction_product_base_queryset
            .values('product_id', 'product__title', 'auction_id', 'auction__name')
            .annotate(
                visit_count=Count('id'),
                last_visit=Max('timestamp'),
            )
            .order_by('-last_visit', '-visit_count', 'product__title')
        )
    elif visit_type == 'auctions':
        queryset = (
            auction_base_queryset
            .values('auction_id', 'auction__name')
            .annotate(
                visit_count=Count('id'),
                last_visit=Max('timestamp'),
            )
            .order_by('-last_visit', '-visit_count', 'auction__name')
        )
    else:
        queryset = (
            store_base_queryset
            .values('product_id', 'product__title')
            .annotate(
                visit_count=Count('id'),
                last_visit=Max('timestamp'),
            )
            .order_by('-last_visit', '-visit_count', 'product__title')
        )

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    results = []
    for visit in page_obj.object_list:
        if visit_type == 'auction_products':
            results.append({
                'product_id': visit['product_id'],
                'product_title': visit['product__title'] or 'محصول حذف شده/نامشخص',
                'auction_id': visit['auction_id'],
                'auction_name': visit['auction__name'] or 'مزایده نامشخص',
                'visit_count': visit['visit_count'],
                'last_visit': visit['last_visit'].isoformat() if visit['last_visit'] else None,
            })
        elif visit_type == 'auctions':
            results.append({
                'auction_id': visit['auction_id'],
                'auction_name': visit['auction__name'] or 'مزایده نامشخص',
                'visit_count': visit['visit_count'],
                'last_visit': visit['last_visit'].isoformat() if visit['last_visit'] else None,
            })
        else:
            results.append({
                'product_id': visit['product_id'],
                'product_title': visit['product__title'] or 'محصول حذف شده/نامشخص',
                'visit_count': visit['visit_count'],
                'last_visit': visit['last_visit'].isoformat() if visit['last_visit'] else None,
            })

    summary = {
        'store_products': store_summary,
        'auction_products': auction_product_summary,
        'auctions': auction_summary,
        'grand_total_visits': (
            store_summary['total_visits']
            + auction_product_summary['total_visits']
            + auction_summary['total_visits']
        ),
        'grand_total_items': (
            store_summary['total_items']
            + auction_product_summary['total_items']
            + auction_summary['total_items']
        ),
    }

    current_summary = summary[visit_type]

    return JsonResponse({
        'type': visit_type,
        'results': results,
        'total': paginator.count,
        'total_visit_count': current_summary['total_visits'],
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
        'summary': summary,
    })


@staff_required
@require_http_methods(['GET'])
def user_bids_api(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    queryset = Bid.objects.filter(user=user).select_related('auction', 'product').order_by('-created_at')

    search = request.GET.get('search', '').strip()
    if search:
        queryset = queryset.filter(
            Q(product__title__icontains=search)
            | Q(product__product_id__icontains=search)
            | Q(auction__name__icontains=search)
        )

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    results = []
    for bid in page_obj.object_list:
        results.append({
            'id': bid.id,
            'auction_id': bid.auction_id,
            'auction_name': bid.auction.name or f'مزایده {bid.auction_id}' if bid.auction else '-',
            'product_id': bid.product_id,
            'product_title': bid.product.title if bid.product else '-',
            'bid_amount': str(bid.bid_amount),
            'user_fullname': bid.user_fullname or '-',
            'user_mobile': bid.user_mobile or '-',
            'created_at': bid.created_at.isoformat() if bid.created_at else None,
        })

    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def user_bids(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    queryset = Bid.objects.filter(user=user).select_related('auction', 'product').order_by('-created_at')

    search = request.GET.get('search', '').strip()
    if search:
        queryset = queryset.filter(
            Q(product__title__icontains=search)
            | Q(product__product_id__icontains=search)
            | Q(auction__name__icontains=search)
        )

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    results = []
    for bid in page_obj.object_list:
        results.append({
            'id': bid.id,
            'auction_id': bid.auction_id,
            'auction_name': bid.auction.name or f'مزایده {bid.auction_id}' if bid.auction else '-',
            'product_id': bid.product_id,
            'product_title': bid.product.title if bid.product else '-',
            'bid_amount': str(bid.bid_amount),
            'user_fullname': bid.user_fullname or '-',
            'user_mobile': bid.user_mobile or '-',
            'created_at': bid.created_at.isoformat() if bid.created_at else None,
        })

    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def user_purchased_products_api(request, pk):
    """
    API برای دریافت محصولات خریداری شده توسط کاربر
    """
    user = get_object_or_404(CustomUser, pk=pk)
    
    # محصولات خریداری شده از فروشگاه
    purchases = PurchaseHistory.objects.filter(user=user).select_related('artwork').order_by('-created_at')
    
    search = request.GET.get('search', '').strip()
    if search:
        purchases = purchases.filter(
            Q(artwork__title__icontains=search) |
            Q(artwork__artist__name__icontains=search)
        )
    
    paginator = Paginator(purchases, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    results = []
    for purchase in page_obj.object_list:
        artwork = purchase.artwork
        results.append({
            'id': purchase.id,
            'artwork_id': artwork.id,
            'title': artwork.title or '-',
            'artist': artwork.artist.name if artwork.artist else '-',
            'price': str(artwork.price or 0),
            'created_at': purchase.created_at.isoformat() if purchase.created_at else None,
            'image_url': artwork.image.url if artwork.image else '',
        })
    
    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def user_cart_bids_summary_api(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    now = timezone.now()
    profile_context = build_profile_live_context(user)

    cart_items = (
        AuctionCartItem.objects
        .filter(user=user)
        .select_related('auction', 'product__artist', 'bid')
        .order_by('-updated_at', '-created_at')
    )

    search = request.GET.get('search', '').strip()
    if search:
        cart_items = cart_items.filter(
            Q(product__title__icontains=search)
            | Q(auction__name__icontains=search)
            | Q(product__artist__name__icontains=search)
        )

    paginator = Paginator(cart_items, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    page_items = list(page_obj.object_list)
    product_ids = [item.product_id for item in page_items if item.product_id]

    bids_by_product = {}
    if product_ids:
        bids_queryset = (
            Bid.objects
            .filter(user=user, product_id__in=product_ids)
            .select_related('auction', 'product')
            .order_by('-created_at')
        )
        for bid in bids_queryset:
            bids_by_product.setdefault(bid.product_id, []).append({
                'id': bid.id,
                'auction_name': bid.auction.name if bid.auction else '-',
                'bid_amount': str(bid.bid_amount),
                'created_at': bid.created_at.isoformat() if bid.created_at else None,
            })

    active_cart_items = cart_items.filter(
        is_active=True,
        auction__start_date__lte=now,
        auction__end_date__gte=now,
    )
    active_count = active_cart_items.count()
    reserved_total_amount = sum(
        (item.reserved_amount for item in active_cart_items),
        start=Decimal('0'),
    )

    results = []
    for item in page_items:
        product_bids = bids_by_product.get(item.product_id, [])
        results.append({
            'id': item.id,
            'auction_id': item.auction_id,
            'auction_name': item.auction.name if item.auction else '-',
            'product_id': item.product_id,
            'product_title': item.product.title if item.product else '-',
            'artist_name': item.product.artist.name if item.product and item.product.artist else '-',
            'reserved_amount': str(item.reserved_amount or 0),
            'latest_bid_amount': str(item.bid.bid_amount) if item.bid else '0',
            'is_active': item.is_active,
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'updated_at': item.updated_at.isoformat() if item.updated_at else None,
            'bid_count': len(product_bids),
            'bids': product_bids,
        })

    return JsonResponse({
        'html': render_to_string(
            'registration/partials/profile_auction_cart.html',
            profile_context,
            request=request,
        ),
        'results': results,
        'total': paginator.count,
        'active_total': active_count,
        'current_total': len(profile_context.get('current_auction_cart_items', [])),
        'past_total': len(profile_context.get('past_auction_cart_items', [])),
        'reserved_total_amount': str(reserved_total_amount),
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def user_reserved_products_api(request, pk):
    """
    API برای دریافت محصولات در حال رزرو (سبد مزایده) کاربر
    """
    user = get_object_or_404(CustomUser, pk=pk)
    now = timezone.now()
    
    # محصولات رزرو شده در مزایده
    cart_items = (
        AuctionCartItem.objects
        .filter(
            user=user,
            is_active=True,
            auction__start_date__lte=now,
            auction__end_date__gte=now,
        )
        .select_related('auction', 'product', 'bid')
        .order_by('-created_at')
    )
    
    search = request.GET.get('search', '').strip()
    if search:
        cart_items = cart_items.filter(
            Q(product__title__icontains=search) |
            Q(auction__name__icontains=search)
        )
    
    paginator = Paginator(cart_items, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    results = []
    for item in page_obj.object_list:
        results.append({
            'id': item.id,
            'auction_id': item.auction_id,
            'auction_name': item.auction.name if item.auction else '-',
            'product_id': item.product_id,
            'product_title': item.product.title if item.product else '-',
            'reserved_amount': str(item.reserved_amount),
            'bid_amount': str(item.bid.bid_amount) if item.bid else '0',
            'is_active': item.is_active,
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'updated_at': item.updated_at.isoformat() if item.updated_at else None,
        })
    
    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def user_purchase_requests_summary_api(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    profile_context = build_profile_live_context(user)
    store_purchases = profile_context.get('store_purchases', [])
    auction_purchases = profile_context.get('auction_purchases', [])

    return JsonResponse({
        'html': render_to_string(
            'registration/partials/profile_purchase_sections.html',
            profile_context,
            request=request,
        ),
        'results': [],
        'total': len(store_purchases) + len(auction_purchases),
        'store_purchases_total': len(store_purchases),
        'auction_purchases_total': len(auction_purchases),
        'purchased_total': len(store_purchases) + len(auction_purchases),
        'reserved_total': 0,
        'pages': 1,
        'current_page': 1,
    })


@require_http_methods(['GET'])
@staff_required
def user_telegram_requests_api(request, pk):
    """
    API برای دریافت درخواست‌های خرید تلگرامی کاربر
    """
    user = get_object_or_404(CustomUser, pk=pk)
    
    telegram_requests = (
        TelegramPurchaseRequest.objects
        .filter(user=user)
        .select_related('artwork')
        .order_by('-created_at')
    )
    
    search = request.GET.get('search', '').strip()
    if search:
        telegram_requests = telegram_requests.filter(
            Q(artwork__title__icontains=search) |
            Q(status__icontains=search)
        )
    
    paginator = Paginator(telegram_requests, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    results = []
    for req in page_obj.object_list:
        artwork = req.artwork
        results.append({
            'id': req.id,
            'token': str(req.token),
            'artwork_id': artwork.id,
            'artwork_title': artwork.title or '-',
            'status': req.status,
            'status_display': req.get_status_display(),
            'telegram_chat_id': req.telegram_chat_id or '-',
            'created_at': req.created_at.isoformat() if req.created_at else None,
        })
    
    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })
