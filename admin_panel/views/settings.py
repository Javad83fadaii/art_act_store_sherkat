import json

from django.conf import settings as django_settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from core.decorators import log_admin_action, staff_required
from core.models import NotificationPreference, SavedFilter


def _request_payload(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return request.POST.dict()


@staff_required
def page_view(request):
    return render(request, 'admin_panel/settings.html')


@staff_required
def get_settings(request):
    data = {
        'session_cookie_httponly': getattr(django_settings, 'SESSION_COOKIE_HTTPONLY', None),
        'session_cookie_secure': getattr(django_settings, 'SESSION_COOKIE_SECURE', None),
        'session_cookie_samesite': getattr(django_settings, 'SESSION_COOKIE_SAMESITE', None),
        'session_cookie_age': getattr(django_settings, 'SESSION_COOKIE_AGE', None),
        'cache_backend': django_settings.CACHES['default']['BACKEND'],
    }
    return JsonResponse(data)


@require_http_methods(['GET', 'POST'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
@log_admin_action('update')
def set_default_filter(request, pk):
    saved_filter = get_object_or_404(SavedFilter, pk=pk, user=request.user)
    SavedFilter.objects.filter(user=request.user, page=saved_filter.page).update(is_default=False)
    saved_filter.is_default = True
    saved_filter.save(update_fields=['is_default'])
    return JsonResponse({'id': saved_filter.pk, 'is_default': saved_filter.is_default})
