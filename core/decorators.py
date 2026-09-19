from functools import wraps

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import JsonResponse

from .models import AdminActivityLog
from .utils import broadcast_admin_panel_refresh


from .logging_service import record_admin_activity


def _admin_forbidden_response(message='Unauthorized'):
    return JsonResponse({'error': message}, status=403)


def staff_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return _admin_forbidden_response()
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return _admin_forbidden_response('Forbidden')
        return view_func(request, *args, **kwargs)

    return wrapper


def log_admin_action(action_type):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)

            is_success = getattr(response, 'status_code', 500) < 400
            is_staff_user = request.user.is_authenticated and request.user.is_staff
            if is_success and is_staff_user and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                target_id = kwargs.get('pk') or kwargs.get('id') or ''
                # اگر در متد ویو لاگ اختصاصی ثبت نشده باشد، لاگ جنریک ثبت می‌شود
                if not getattr(request, '_admin_log_recorded', False):
                    record_admin_activity(
                        admin_user=request.user,
                        action=action_type,
                        target_id=str(target_id) if target_id else '',
                        request=request,
                    )

            return response

        return wrapper

    return decorator
