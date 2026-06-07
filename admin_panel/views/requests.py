import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from django.core.exceptions import ValidationError
from django.db.models import Case, CharField, F, IntegerField, Value, When
from django.shortcuts import render
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from accounts.models import CreditIncreaseRequest, VerificationRequest
from core.decorators import log_admin_action, staff_required
from core.models import TemplateMessage
from core.utils import cache_response, invalidate_cache, broadcast_admin_panel_refresh
from store.models import TelegramPurchaseRequest, Artwork

REQUEST_MODELS = {
    'verification': VerificationRequest,
    'credit': CreditIncreaseRequest,
    'purchase': TelegramPurchaseRequest,
}

REQUESTS_PAGE_SIZE = 100
MIN_ADMIN_CREDIT_AMOUNT = Decimal('500000000')

PURCHASE_STATUS_SORT_ORDER = {
    'pending': 0,
    'confirmed': 1,
    'contacted': 2,
    'rejected': 3,
}

NUMERIC_STATUS_MAP = {
    'pending': 0,
    'approved': 1,
    'rejected': 2,
}


def _request_status_to_api(status_value):
    mapping = {
        0: 'pending',
        1: 'approved',
        2: 'rejected',
    }
    return mapping.get(int(status_value or 0), 'pending')


def _format_currency(value):
    if value is None:
        return 'نامشخص'
    return f"${float(value):,.2f}"


def _parse_request_sort_fields(sort_param):
    sort_fields = []
    seen = set()
    for raw_field in (sort_param or '').split(','):
        raw_field = raw_field.strip()
        if not raw_field:
            continue
        direction = '-' if raw_field.startswith('-') else ''
        field_name = raw_field.lstrip('-')
        if field_name not in {'user', 'status'} or field_name in seen:
            continue
        sort_fields.append((field_name, direction))
        seen.add(field_name)
    return sort_fields


def _apply_request_ordering(queryset, sort_param):
    ordering = []
    for field_name, direction in _parse_request_sort_fields(sort_param):
        if field_name == 'user':
            ordering.append(f'{direction}user_sort_value')
        elif field_name == 'status':
            ordering.append(f'{direction}status_sort_value')
    ordering.extend(['-created_at', '-pk'])
    return queryset.order_by(*ordering)


def _purchase_queryset():
    return TelegramPurchaseRequest.objects.select_related('user', 'artwork').annotate(
        user_sort_value=Case(
            When(user__full_name__gt='', then=F('user__full_name')),
            When(user__phone_number__gt='', then=F('user__phone_number')),
            When(user__email__gt='', then=F('user__email')),
            When(user__username__gt='', then=F('user__username')),
            default=Value(''),
            output_field=CharField(),
        ),
        status_sort_value=Case(
            *[
                When(status=status_name, then=Value(sort_order))
                for status_name, sort_order in PURCHASE_STATUS_SORT_ORDER.items()
            ],
            default=Value(99),
            output_field=IntegerField(),
        ),
    )


def _verification_queryset():
    return VerificationRequest.objects.select_related('user').annotate(
        user_sort_value=Case(
            When(full_name__gt='', then=F('full_name')),
            When(user__full_name__gt='', then=F('user__full_name')),
            When(phone_number__gt='', then=F('phone_number')),
            When(user__phone_number__gt='', then=F('user__phone_number')),
            When(user__email__gt='', then=F('user__email')),
            When(user__username__gt='', then=F('user__username')),
            default=Value(''),
            output_field=CharField(),
        ),
        status_sort_value=F('status'),
    )


def _credit_queryset():
    return CreditIncreaseRequest.objects.select_related('user').annotate(
        user_sort_value=Case(
            When(user__full_name__gt='', then=F('user__full_name')),
            When(user__phone_number__gt='', then=F('user__phone_number')),
            When(user__email__gt='', then=F('user__email')),
            When(user__username__gt='', then=F('user__username')),
            default=Value(''),
            output_field=CharField(),
        ),
        status_sort_value=F('status'),
    )

def _request_payload(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return request.POST.dict()


def _format_user_full_name(user, fallback_full_name=''):
    full_name = (fallback_full_name or '').strip()
    if not full_name and user is not None:
        full_name = (
            (getattr(user, 'full_name', '') or '').strip()
            or (getattr(user, 'get_full_name', lambda: '')() or '').strip()
        )

    if not full_name and user is not None:
        first_name = (getattr(user, 'first_name', '') or '').strip()
        last_name = (getattr(user, 'last_name', '') or '').strip()
        full_name = ' '.join(part for part in [first_name, last_name] if part).strip()

    return full_name


def _serialize_request_user(user, fallback_full_name='', fallback_phone_number=''):
    if user is None:
        return {
            'username': '',
            'full_name': (fallback_full_name or '').strip(),
            'first_name': '',
            'last_name': '',
            'phone_number': (fallback_phone_number or '').strip(),
            'email': '',
            'is_verified': False,
            'total_credit': None,
            'current_credit': None,
            'preferred_contact_methods': [],
            'telegram_id': '',
        }

    return {
        'username': getattr(user, 'username', '') or '',
        'full_name': _format_user_full_name(user, fallback_full_name=fallback_full_name),
        'first_name': (getattr(user, 'first_name', '') or '').strip(),
        'last_name': (getattr(user, 'last_name', '') or '').strip(),
        'phone_number': (fallback_phone_number or getattr(user, 'phone_number', '') or '').strip(),
        'email': getattr(user, 'email', '') or '',
        'is_verified': bool(int(getattr(user, 'is_verified', 0) or 0)),
        'total_credit': getattr(user, 'credit', None),
        'current_credit': getattr(user, 'current_credit', None),
        'preferred_contact_methods': getattr(user, 'preferred_contact_methods', []) or [],
        'telegram_id': getattr(user, 'telegram_id', '') or '',
    }


def _request_user_label(user, fallback_full_name='', fallback_phone_number=''):
    user_data = _serialize_request_user(
        user,
        fallback_full_name=fallback_full_name,
        fallback_phone_number=fallback_phone_number,
    )
    return (
        user_data['full_name']
        or user_data['phone_number']
        or user_data['email']
        or user_data['username']
        or 'نامشخص'
    )


def _serialize_request_list_item(request_type, item):
    if request_type == 'purchase':
        return {
            'id': item.id,
            'user_id': str(item.user_id) if getattr(item, 'user_id', None) else None,
            'user': _request_user_label(item.user),
            'product': item.artwork.title if item.artwork else 'نامشخص',
            'created_at': item.created_at.isoformat() if getattr(item, 'created_at', None) else None,
            'status': item.status,
        }

    if request_type == 'verification':
        return {
            'id': item.id,
            'user_id': str(item.user_id) if getattr(item, 'user_id', None) else None,
            'user': _request_user_label(
                item.user,
                fallback_full_name=getattr(item, 'full_name', ''),
                fallback_phone_number=getattr(item, 'phone_number', ''),
            ),
            'product': getattr(item, 'phone_number', '') or '---',
            'created_at': item.created_at.isoformat() if getattr(item, 'created_at', None) else None,
            'status': _request_status_to_api(item.status),
        }

    return {
        'id': item.id,
        'user_id': str(item.user_id) if getattr(item, 'user_id', None) else None,
        'user': _request_user_label(item.user),
        'product': _format_currency(getattr(item.user, 'current_credit', None)) if item.user_id else 'نامشخص',
        'current_credit': _format_currency(getattr(item.user, 'current_credit', None)) if item.user_id else 'نامشخص',
        'requested_credit': _format_currency(item.current_credit) if item.current_credit is not None else 'مبلغ نامشخص',
        'total_credit': _format_currency(getattr(item.user, 'credit', 0) if item.user_id else None),
        'created_at': item.created_at.isoformat() if getattr(item, 'created_at', None) else None,
        'status': _request_status_to_api(item.status),
    }


def _validation_error_response(exc):
    if hasattr(exc, 'message_dict'):
        errors = exc.message_dict
        messages = []
        for field_errors in errors.values():
            if isinstance(field_errors, (list, tuple)):
                messages.extend(str(item) for item in field_errors if item)
            elif field_errors:
                messages.append(str(field_errors))
        message = messages[0] if messages else 'اعتبارسنجی درخواست با خطا مواجه شد.'
        return JsonResponse({'error': message, 'errors': errors}, status=400)

    messages = getattr(exc, 'messages', None) or ['اعتبارسنجی درخواست با خطا مواجه شد.']
    return JsonResponse({'error': messages[0], 'errors': {'__all__': messages}}, status=400)


def _format_admin_credit_amount(value):
    return f'{int(value):,}'.replace(',', '.')


def _parse_admin_credit_amount(amount, *, required):
    if amount in (None, ''):
        if required:
            return None, JsonResponse(
                {'error': f'مبلغ باید حداقل {_format_admin_credit_amount(MIN_ADMIN_CREDIT_AMOUNT)} باشد.'},
                status=400,
            )
        return None, None

    try:
        amount_value = Decimal(str(amount))
    except (TypeError, ValueError, InvalidOperation):
        return None, JsonResponse({'error': 'مبلغ نامعتبر است. لطفاً عدد وارد کنید.'}, status=400)

    if amount_value < MIN_ADMIN_CREDIT_AMOUNT:
        return None, JsonResponse(
            {'error': f'حداقل مبلغ قابل تخصیص {_format_admin_credit_amount(MIN_ADMIN_CREDIT_AMOUNT)} است.'},
            status=400,
        )

    return amount_value, None

@staff_required
@cache_response(timeout=180, key_prefix='admin_requests')
def list_view(request):
    request_type = request.GET.get('type', 'purchase')
    status = request.GET.get('status')
    sort_param = request.GET.get('sort', '')
    page_number = request.GET.get('page', 1)

    if request_type == 'purchase':
        requests_qs = _purchase_queryset()
        if status:
            requests_qs = requests_qs.filter(status=status)
        requests_qs = _apply_request_ordering(requests_qs, sort_param)
        paginator = Paginator(requests_qs, REQUESTS_PAGE_SIZE)
        page = paginator.get_page(page_number)
        payload = [_serialize_request_list_item('purchase', item) for item in page.object_list]
        return JsonResponse(
            {
                'requests': payload,
                'total': paginator.count,
                'pages': paginator.num_pages,
                'current_page': page.number,
                'page_size': REQUESTS_PAGE_SIZE,
            }
        )

    if request_type == 'verification':
        requests_qs = _verification_queryset()
        if status in NUMERIC_STATUS_MAP:
            requests_qs = requests_qs.filter(status=NUMERIC_STATUS_MAP[status])
        requests_qs = _apply_request_ordering(requests_qs, sort_param)
        paginator = Paginator(requests_qs, REQUESTS_PAGE_SIZE)
        page = paginator.get_page(page_number)
        payload = [_serialize_request_list_item('verification', item) for item in page.object_list]
        return JsonResponse(
            {
                'requests': payload,
                'total': paginator.count,
                'pages': paginator.num_pages,
                'current_page': page.number,
                'page_size': REQUESTS_PAGE_SIZE,
            }
        )

    if request_type == 'credit':
        requests_qs = _credit_queryset()
        if status in NUMERIC_STATUS_MAP:
            requests_qs = requests_qs.filter(status=NUMERIC_STATUS_MAP[status])
        requests_qs = _apply_request_ordering(requests_qs, sort_param)
        paginator = Paginator(requests_qs, REQUESTS_PAGE_SIZE)
        page = paginator.get_page(page_number)
        payload = [_serialize_request_list_item('credit', item) for item in page.object_list]
        return JsonResponse(
            {
                'requests': payload,
                'total': paginator.count,
                'pages': paginator.num_pages,
                'current_page': page.number,
                'page_size': REQUESTS_PAGE_SIZE,
            }
        )

    return JsonResponse({'error': 'Invalid request type'}, status=400)


@staff_required
def notifications_feed(request):
    try:
        limit = int(request.GET.get('limit') or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))

    purchase_qs = (
        TelegramPurchaseRequest.objects.select_related('user', 'artwork')
        .filter(status='pending')
        .order_by('-created_at')[:limit]
    )
    verification_qs = (
        VerificationRequest.objects.select_related('user')
        .filter(status=VerificationRequest.RequestStatus.PENDING)
        .order_by('-created_at')[:limit]
    )
    credit_qs = (
        CreditIncreaseRequest.objects.select_related('user')
        .filter(status=0)
        .order_by('-created_at')[:limit]
    )

    items = []

    for obj in purchase_qs:
        user_label = (
            (getattr(obj.user, 'get_full_name', lambda: '')() or '').strip()
            or getattr(obj.user, 'phone_number', None)
            or getattr(obj.user, 'username', '')
        )
        product_title = obj.artwork.title if obj.artwork else 'نامشخص'
        items.append(
            {
                'type': 'purchase_request',
                'title': 'درخواست جدید خرید',
                'message': f'{user_label} برای «{product_title}» درخواست ثبت کرد.',
                'timestamp': obj.created_at.astimezone(timezone.utc).isoformat()
                if getattr(obj, 'created_at', None)
                else datetime.now(timezone.utc).isoformat(),
                'data': {'request_type': 'purchase', 'id': obj.pk},
                'href': '/admin-panel/requests/?type=purchase',
            }
        )

    for obj in verification_qs:
        user_label = (
            (getattr(obj.user, 'get_full_name', lambda: '')() or '').strip()
            or getattr(obj.user, 'phone_number', None)
            or getattr(obj.user, 'username', '')
        )
        items.append(
            {
                'type': 'verification_request',
                'title': 'درخواست جدید تایید مزایده',
                'message': f'{user_label} درخواست تایید مزایده ثبت کرد.',
                'timestamp': obj.created_at.astimezone(timezone.utc).isoformat()
                if getattr(obj, 'created_at', None)
                else datetime.now(timezone.utc).isoformat(),
                'data': {'request_type': 'verification', 'id': obj.pk},
                'href': '/admin-panel/requests/?type=verification',
            }
        )

    for obj in credit_qs:
        user_label = (
            (getattr(obj.user, 'get_full_name', lambda: '')() or '').strip()
            or getattr(obj.user, 'phone_number', None)
            or getattr(obj.user, 'username', '')
        )
        items.append(
            {
                'type': 'credit_request',
                'title': 'درخواست جدید افزایش اعتبار',
                'message': f'{user_label} درخواست افزایش اعتبار ثبت کرد.',
                'timestamp': obj.created_at.astimezone(timezone.utc).isoformat()
                if getattr(obj, 'created_at', None)
                else datetime.now(timezone.utc).isoformat(),
                'data': {'request_type': 'credit', 'id': obj.pk},
                'href': '/admin-panel/requests/?type=credit',
            }
        )

    items.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
    items = items[:limit]

    return JsonResponse(
        {
            'items': items,
            'counts': {
                'purchase_pending': TelegramPurchaseRequest.objects.filter(status='pending').count(),
                'verification_pending': VerificationRequest.objects.filter(
                    status=VerificationRequest.RequestStatus.PENDING
                ).count(),
                'credit_pending': CreditIncreaseRequest.objects.filter(
                    status=CreditIncreaseRequest.RequestStatus.PENDING
                ).count(),
            },
        }
    )


@require_http_methods(['GET', 'POST'])
@staff_required
@log_admin_action('update')
def detail_view(request, request_type, pk):
    model = REQUEST_MODELS.get(request_type)
    if model is None:
        return JsonResponse({'error': 'Invalid request type'}, status=400)

    if request_type == 'purchase':
        obj = get_object_or_404(model.objects.select_related('user', 'artwork'), pk=pk)
    elif request_type in ['credit', 'verification']:
        obj = get_object_or_404(model.objects.select_related('user'), pk=pk)
    else:
        obj = get_object_or_404(model, pk=pk)

    if request.method == 'POST':
        payload = _request_payload(request)
        action = payload.get('action')

        if request_type == 'purchase':
            if action == 'approve':
                if obj.artwork:
                    obj.artwork.is_sold = Artwork.IsSoldStatus.SOLD
                    obj.artwork.save(update_fields=['is_sold', 'updated_at'])
                obj.status = 'confirmed'
                obj.save(update_fields=['status', 'updated_at'])
            elif action == 'reject':
                obj.status = 'rejected'
                obj.save(update_fields=['status', 'updated_at'])
                if obj.artwork:
                    obj.artwork.is_sold = Artwork.IsSoldStatus.AVAILABLE
                    obj.artwork.save(update_fields=['is_sold', 'updated_at'])
                
        elif request_type == 'verification':
            if action == 'approve':
                amount = payload.get('amount')
                if amount not in (None, ''):
                    amount_value, error_response = _parse_admin_credit_amount(amount, required=False)
                    if error_response is not None:
                        return error_response
                    obj.granted_credit = amount_value

                obj.status = VerificationRequest.RequestStatus.APPROVED
                try:
                    obj.save()
                except ValidationError as exc:
                    return _validation_error_response(exc)

            elif action == 'reject':
                obj.status = VerificationRequest.RequestStatus.REJECTED
                try:
                    obj.save()
                except ValidationError as exc:
                    return _validation_error_response(exc)

        elif request_type == 'credit':
            if action == 'approve':
                amount = payload.get('amount')
                amount, error_response = _parse_admin_credit_amount(amount, required=True)
                if error_response is not None:
                    return error_response

                # بررسی وریفای بودن کاربر پیش از تایید درخواست طبق مدل
                if int(obj.user.is_verified or 0) == 0:
                    return JsonResponse({'error': 'نمی‌توانید درخواست افزایش اعتبار را برای کاربری که وریفای نشده (وضعیت 0) تایید کنید.'}, status=400)

                try:
                    # تنظیم مبلغ و وضعیت، مدل هنگام save موجودی کاربر را آپدیت می‌کند
                    obj.current_credit = amount
                    obj.status = 1  # APPROVED
                    obj.save()

                except ValidationError as exc:
                    return _validation_error_response(exc)
                except Exception as e:
                    return JsonResponse({'error': f'خطای سرور: {str(e)}'}, status=500)
                
            elif action == 'reject':
                obj.status = 2  # REJECTED
                try:
                    obj.save(update_fields=['status'])
                except ValidationError as exc:
                    return _validation_error_response(exc)

        invalidate_cache('admin_requests*')
        invalidate_cache('admin_request_detail*')
        invalidate_cache('admin_dashboard*')
        broadcast_admin_panel_refresh(
            actor=request.user,
            action_type=f'request_{action}',
            path=request.path,
            object_id=pk
        )
        return JsonResponse({'success': True, 'updated': True})

    fields = {'id': obj.pk, 'request_type': request_type}
    user = getattr(obj, 'user', None)

    if request_type == 'verification':
        fields.update(
            _serialize_request_user(
                user,
                fallback_full_name=getattr(obj, 'full_name', ''),
                fallback_phone_number=getattr(obj, 'phone_number', ''),
            )
        )
        fields['granted_credit'] = getattr(obj, 'granted_credit', None)
    else:
        fields.update(_serialize_request_user(user))

    if request_type == 'purchase':
        fields['product'] = obj.artwork.title if obj.artwork else 'نامشخص'
        fields['price'] = getattr(obj.artwork, 'price', None) if obj.artwork else None
        preferred_methods = fields.pop('preferred_contact_methods', []) or []
        contact_labels = []
        method_map = {
            'phone': 'تلفن',
            'whatsapp': 'واتساپ',
            'telegram': 'تلگرام',
            'email': 'ایمیل',
        }
        for method in preferred_methods:
            label = method_map.get(str(method).lower())
            if label:
                contact_labels.append(label)
        if fields.get('phone_number'):
            contact_labels.insert(0, fields['phone_number'])
        if fields.get('telegram_id'):
            contact_labels.append(f"تلگرام: {fields['telegram_id']}")
        if fields.get('email'):
            contact_labels.append(f"ایمیل: {fields['email']}")
        fields['contact_ways'] = ' | '.join(dict.fromkeys([item for item in contact_labels if item])) or 'ثبت نشده'
        fields['telegram_chat_id'] = getattr(obj, 'telegram_chat_id', None)
    elif request_type == 'credit':
        fields['requested_credit'] = getattr(obj, 'current_credit', None)

    # دریافت فیلدهای متداول
    for field_name in ('created_at', 'updated_at', 'status'):
        if hasattr(obj, field_name):
            value = getattr(obj, field_name)
            
            # تبدیل وضعیت عددی کردیت به متن برای نمایش در مودال
            if request_type == 'credit' and field_name == 'status':
                value = _request_status_to_api(value)
            elif request_type == 'verification' and field_name == 'status':
                value = _request_status_to_api(value)
                    
            fields[field_name] = value.isoformat() if hasattr(value, 'isoformat') else value

    for relation_name in ('user_id', 'artwork_id'):
        value = getattr(obj, relation_name, None)
        if value is not None:
            fields[relation_name] = str(value)

    return JsonResponse(fields)


@require_http_methods(['POST'])
@staff_required
@log_admin_action('bulk_action')
def bulk_action(request):
    return JsonResponse(
        {'error': 'عملیات گروهی درخواست‌ها از پنل مدیریت حذف شده است. لطفاً هر درخواست را به‌صورت تکی بررسی کنید.'},
        status=405,
    )


@require_http_methods(['GET'])
@staff_required
def templates_list(request):
    templates = TemplateMessage.objects.filter(active=True).order_by('category', 'title')
    data = [
        {
            'id': t.id,
            'title': t.title,
            'category': t.category,
            'content': t.content,
        }
        for t in templates
    ]
    return JsonResponse({'templates': data})


@staff_required
def page_view(request):
    return render(request, 'admin_panel/requests.html')
