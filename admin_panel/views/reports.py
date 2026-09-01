import csv

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods
from django.db.models import Q

from accounts.models import CustomUser
from auction.models import AuctionVisitHistory
from core.decorators import log_admin_action, superuser_required
from core.logging_service import record_admin_activity
from core.models import AdminActivityLog, ErrorLog
from core.utils import cache_response


@superuser_required
def page_view(request):
    return render(request, 'admin_panel/reports.html')


@superuser_required
def activity_logs(request):
    logs = AdminActivityLog.objects.select_related('admin_user').order_by('-timestamp')[:100]
    payload = [
        {
            'admin': log.admin_user.get_full_name() or log.admin_user.username,
            'action': log.description or log.action,
            'timestamp': log.timestamp.isoformat(),
        }
        for log in logs
    ]
    return JsonResponse({'logs': payload})


@superuser_required
@cache_response(timeout=60, key_prefix='admin_report_error_logs')
def error_logs(request):
    logs = list(
        ErrorLog.objects.select_related('user')
        .order_by('-timestamp')
        .values(
            'id',
            'error_type',
            'url',
            'method',
            'resolved',
            'timestamp',
            'user__full_name',
            'user__phone_number',
        )[:100]
    )
    return JsonResponse({'results': logs})


@require_http_methods(['POST'])
@superuser_required
@log_admin_action('approve')
def resolve_error(request, pk):
    error = get_object_or_404(ErrorLog, pk=pk)
    error.resolved = True
    error.save(update_fields=['resolved'])

    record_admin_activity(
        admin_user=request.user,
        action='error_resolve',
        description=f"برطرف کردن خطای سرور #{error.pk} ({error.error_type} روی {error.url})",
        target_type='خطای سرور',
        target_id=str(error.pk),
        target_repr=f"Error #{error.pk} ({error.error_type})",
        changes={'resolved': {'old': False, 'new': True}},
        request=request,
    )
    request._admin_log_recorded = True

    return JsonResponse({'id': error.pk, 'resolved': error.resolved})


@superuser_required
def admin_logs(request):
    search = request.GET.get('search', '').strip()
    action_filter = request.GET.get('action', '').strip()
    target_type_filter = request.GET.get('target_type', '').strip()

    logs_qs = AdminActivityLog.objects.select_related('admin_user').order_by('-timestamp')

    if action_filter:
        logs_qs = logs_qs.filter(action__icontains=action_filter)

    if target_type_filter:
        logs_qs = logs_qs.filter(target_type__icontains=target_type_filter)

    if search:
        logs_qs = logs_qs.filter(
            Q(description__icontains=search)
            | Q(target_repr__icontains=search)
            | Q(target_id__icontains=search)
            | Q(admin_user__full_name__icontains=search)
            | Q(admin_user__phone_number__icontains=search)
            | Q(ip_address__icontains=search)
        )

    results = []
    for log in logs_qs[:200]:
        admin_display = (
            log.admin_user.get_full_name()
            or getattr(log.admin_user, 'phone_number', '')
            or getattr(log.admin_user, 'username', 'نامشخص')
        )
        results.append({
            'id': log.id,
            'action': log.action,
            'description': log.description or '',
            'target_type': log.target_type or 'عمومی',
            'target_id': log.target_id or '',
            'target_repr': log.target_repr or '',
            'changes': log.changes or {},
            'ip_address': log.ip_address or '-',
            'timestamp': log.timestamp.isoformat(),
            'admin_user__full_name': admin_display,
        })

    return JsonResponse({'results': results})


@superuser_required
@cache_response(timeout=120, key_prefix='admin_report_auction_visit_logs')
def auction_visit_logs(request):
    scope = request.GET.get('scope', 'all')
    auction_id = request.GET.get('auction_id')
    product_id = request.GET.get('product_id')
    search = request.GET.get('search', '').strip()

    visits = AuctionVisitHistory.objects.select_related('user', 'auction', 'product').order_by('-timestamp')

    if scope == 'auction':
        visits = visits.filter(product__isnull=True)
    elif scope == 'product':
        visits = visits.filter(product__isnull=False)

    if auction_id and auction_id.isdigit():
        visits = visits.filter(auction_id=int(auction_id))

    if product_id and product_id.isdigit():
        visits = visits.filter(product_id=int(product_id))

    if search:
        visits = visits.filter(
            Q(auction__name__icontains=search)
            | Q(product__title__icontains=search)
            | Q(user__full_name__icontains=search)
            | Q(user__phone_number__icontains=search)
            | Q(ip_address__icontains=search)
        )

    payload = [
        {
            'id': visit.id,
            'scope': 'product' if visit.product_id else 'auction',
            'scope_label': 'محصول مزایده' if visit.product_id else 'مزایده',
            'auction_id': visit.auction_id,
            'auction_title': visit.auction.name or f'مزایده {visit.auction_id}',
            'product_id': visit.product_id,
            'product_title': visit.product.title if visit.product_id else '',
            'visitor': (
                (visit.user.get_full_name() or getattr(visit.user, 'phone_number', '') or getattr(visit.user, 'username', ''))
                if visit.user_id else 'کاربر مهمان'
            ),
            'user_id': str(visit.user_id) if visit.user_id else None,
            'ip_address': visit.ip_address,
            'timestamp': visit.timestamp.isoformat(),
        }
        for visit in visits[:200]
    ]

    return JsonResponse({'results': payload})


@superuser_required
@cache_response(timeout=60, key_prefix='admin_report_export')
def export_data(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users.csv"'

    writer = csv.writer(response)
    writer.writerow(['Username', 'Email', 'Active'])
    for user in CustomUser.objects.order_by('username'):
        writer.writerow([user.username, user.email or '', user.is_active])

    return response
