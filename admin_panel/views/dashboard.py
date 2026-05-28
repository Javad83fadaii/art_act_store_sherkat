from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db.models import Count, DateField, Sum
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.models import CreditIncreaseRequest, CustomUser, VerificationRequest
from auction.models import Auction, AuctionProduct, AuctionVisitHistory
from core.decorators import staff_required
from core.models import AdminActivityLog
from core.utils import cache_response
from store.models import Artwork, SiteVisitLog, TelegramPurchaseRequest, VisitHistory


@staff_required
def page_view(request):
    return render(request, 'admin_panel/dashboard.html')


@staff_required
@cache_response(timeout=300, key_prefix='admin_dashboard_stats')
def stats_view(request):
    week_ago = timezone.now() - timedelta(days=7)
    pending_requests = (
        VerificationRequest.objects.filter(
            status=VerificationRequest.RequestStatus.PENDING
        ).count()
        + CreditIncreaseRequest.objects.filter(
            status=CreditIncreaseRequest.RequestStatus.PENDING
        ).count()
        + TelegramPurchaseRequest.objects.filter(status='pending').count()
    )

    return JsonResponse(
        {
            'total_users': CustomUser.objects.count(),
            'active_users_week': CustomUser.objects.filter(last_login__gte=week_ago).count(),
            'auction_products': AuctionProduct.objects.count(),
            'shop_products': Artwork.objects.filter(is_sold=Artwork.IsSoldStatus.AVAILABLE).count(),
            'pending_requests': pending_requests,
        }
    )


@staff_required
@cache_response(timeout=300, key_prefix='admin_dashboard_charts_v3')
def charts_view(request):
    days = max(int(request.GET.get('days', 30) or 30), 1)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    query_tz = timezone.now().tzinfo or dt_timezone.utc
    start_dt = datetime.combine(start, time.min, tzinfo=query_tz)
    end_dt = datetime.combine(today + timedelta(days=1), time.min, tzinfo=query_tz)

    date_range = [start + timedelta(days=i) for i in range(days)]
    labels = [d.isoformat() for d in date_range]

    registrations_qs = (
        CustomUser.objects.filter(date_joined__gte=start_dt, date_joined__lt=end_dt)
        .annotate(day=Cast('date_joined', output_field=DateField()))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    registrations_map = {row['day']: row['count'] for row in registrations_qs}
    registrations_data = [int(registrations_map.get(d, 0)) for d in date_range]

    store_product_visits_qs = (
        VisitHistory.objects.filter(timestamp__gte=start_dt, timestamp__lt=end_dt)
        .annotate(day=Cast('timestamp', output_field=DateField()))
        .values('day')
        .annotate(views=Count('id'))
        .order_by('day')
    )
    store_product_visits_map = {row['day']: row['views'] for row in store_product_visits_qs}
    store_product_visits_data = [int(store_product_visits_map.get(d, 0)) for d in date_range]

    auction_product_visits_qs = (
        AuctionVisitHistory.objects.filter(
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            product__isnull=False,
        )
        .annotate(day=Cast('timestamp', output_field=DateField()))
        .values('day')
        .annotate(views=Count('id'))
        .order_by('day')
    )
    auction_product_visits_map = {row['day']: row['views'] for row in auction_product_visits_qs}
    auction_product_visits_data = [int(auction_product_visits_map.get(d, 0)) for d in date_range]

    return JsonResponse({
        'registrations': {
            'labels': labels,
            'data': registrations_data,
        },
        'visits': {
            'labels': labels,
            'store_products': store_product_visits_data,
            'auction_products': auction_product_visits_data,
        },
    })


def _format_remaining(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return 'پایان یافته'
    minutes = total_seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days > 0:
        return f'{days} روز'
    if hours > 0:
        return f'{hours} ساعت'
    return f'{max(minutes, 1)} دقیقه'


@staff_required
@cache_response(timeout=120, key_prefix='admin_dashboard_orders')
def orders_view(request):
    def _user_label(user):
        if not user:
            return '—'
        return (
            (getattr(user, 'get_full_name', lambda: '')() or '').strip()
            or getattr(user, 'phone_number', '')
            or getattr(user, 'email', '')
            or getattr(user, 'username', '')
            or str(user)
        )

    items = []

    for obj in TelegramPurchaseRequest.objects.select_related('user', 'artwork').order_by('-created_at')[:10]:
        created_at = getattr(obj, 'created_at', None) or timezone.now()
        status_raw = str(getattr(obj, 'status', '') or '').lower()
        status = status_raw if status_raw in {'pending', 'approved', 'confirmed', 'rejected'} else 'pending'
        product_title = obj.artwork.title if getattr(obj, 'artwork', None) else 'نامشخص'
        items.append((created_at, {
            'user': _user_label(getattr(obj, 'user', None)),
            'title': f'درخواست خرید: {product_title}',
            'status': status,
            'date': timezone.localtime(created_at).strftime('%Y-%m-%d %H:%M'),
            'href': reverse('admin_panel_pages:requests') + f'?type=purchase&request_id={obj.pk}',
        }))

    for obj in VerificationRequest.objects.select_related('user').order_by('-created_at')[:10]:
        created_at = getattr(obj, 'created_at', None) or timezone.now()
        status = 'pending'
        if int(getattr(obj, 'status', 0) or 0) == VerificationRequest.RequestStatus.APPROVED:
            status = 'approved'
        elif int(getattr(obj, 'status', 0) or 0) == VerificationRequest.RequestStatus.REJECTED:
            status = 'rejected'
        items.append((created_at, {
            'user': _user_label(getattr(obj, 'user', None)),
            'title': 'درخواست تایید شرکت در مزایده',
            'status': status,
            'date': timezone.localtime(created_at).strftime('%Y-%m-%d %H:%M'),
            'href': reverse('admin_panel_pages:requests') + f'?type=verification&request_id={obj.pk}',
        }))

    for obj in CreditIncreaseRequest.objects.select_related('user').order_by('-created_at')[:10]:
        created_at = getattr(obj, 'created_at', None) or timezone.now()
        st = int(getattr(obj, 'status', 0) or 0)
        status = 'pending'
        if st == 1:
            status = 'approved'
        elif st == 2:
            status = 'rejected'
        amount = getattr(obj, 'current_credit', None)
        amount_label = f'{amount}' if amount not in (None, '') else '—'
        items.append((created_at, {
            'user': _user_label(getattr(obj, 'user', None)),
            'title': f'درخواست افزایش اعتبار: {amount_label}',
            'status': status,
            'date': timezone.localtime(created_at).strftime('%Y-%m-%d %H:%M'),
            'href': reverse('admin_panel_pages:requests') + f'?type=credit&request_id={obj.pk}',
        }))

    items.sort(key=lambda x: x[0], reverse=True)
    payload = [row for _, row in items[:10]]
    return JsonResponse({'requests': payload})


@staff_required
@cache_response(timeout=60, key_prefix='admin_dashboard_ending_auctions')
def ending_auctions_view(request):
    now = timezone.now()
    auctions = (
        Auction.objects.filter(end_date__gte=now)
        .order_by('end_date')[:10]
    )

    payload = []
    for a in auctions:
        remaining = _format_remaining(a.end_date - now) if a.end_date else '—'
        payload.append({
            'title': a.name or f'مزایده {a.pk}',
            'remaining': remaining,
            'url': reverse('admin_panel_pages:products-auctions-detail', args=[a.pk]),
            'image': None,
            'current_price': None,
        })
    return JsonResponse({'auctions': payload})


@staff_required
@cache_response(timeout=120, key_prefix='admin_dashboard_new_users')
def new_users_view(request):
    users = []
    for u in CustomUser.objects.order_by('-date_joined')[:10]:
        name = (u.get_full_name() or '').strip() or getattr(u, 'phone_number', '') or getattr(u, 'email', '') or str(u)
        joined = timezone.localtime(u.date_joined).strftime('%Y-%m-%d')
        users.append({
            'name': name or '—',
            'email': getattr(u, 'email', '') or '',
            'phone': getattr(u, 'phone_number', '') or '',
            'joined': joined,
            'url': reverse('admin_panel_pages:user-history', args=[u.pk]),
            'avatar': None,
        })
    return JsonResponse({'users': users})


@staff_required
@cache_response(timeout=120, key_prefix='admin_dashboard_activities')
def activities_view(request):
    logs = AdminActivityLog.objects.select_related('admin_user').order_by('-timestamp')[:50]
    activities = [
        {
            'admin': log.admin_user.get_full_name() or str(log.admin_user),
            'action': log.action,
            'timestamp': log.timestamp.isoformat(),
        }
        for log in logs
    ]
    return JsonResponse({'activities': activities})
