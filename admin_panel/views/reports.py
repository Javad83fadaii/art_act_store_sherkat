import csv

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods
from django.db.models import Q

from accounts.models import CustomUser
from auction.models import AuctionVisitHistory
from core.decorators import log_admin_action, superuser_required
from core.models import AdminActivityLog, ErrorLog
from core.utils import cache_response


@superuser_required
def page_view(request):
    return render(request, 'admin_panel/reports.html')


@superuser_required
@cache_response(timeout=180, key_prefix='admin_report_activity_logs')
def activity_logs(request):
    logs = AdminActivityLog.objects.select_related('admin_user').order_by('-timestamp')[:100]
    payload = [
        {
            'admin': log.admin_user.username,
            'action': log.action,
            'timestamp': log.timestamp.isoformat(),
        }
        for log in logs
    ]
    return JsonResponse({'logs': payload})


@superuser_required
@cache_response(timeout=180, key_prefix='admin_report_error_logs')
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
    return JsonResponse({'id': error.pk, 'resolved': error.resolved})


@superuser_required
@cache_response(timeout=180, key_prefix='admin_report_admin_logs')
def admin_logs(request):
    logs = list(
        AdminActivityLog.objects.select_related('admin_user')
        .order_by('-timestamp')
        .values('id', 'action', 'object_id', 'changes', 'ip_address', 'timestamp', 'admin_user__full_name')[:100]
    )
    return JsonResponse({'results': logs})


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
