from functools import wraps

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import JsonResponse

from .models import AdminActivityLog
from .utils import broadcast_admin_panel_refresh


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
            if is_success and is_staff_user:
                raw_object_id = kwargs.get('pk', 0)
                object_id = raw_object_id if isinstance(raw_object_id, int) else 0

                AdminActivityLog.objects.create(
                    admin_user=request.user,
                    action=action_type,
                    ip_address=request.META.get('REMOTE_ADDR') or '127.0.0.1',
                    content_type=ContentType.objects.get_for_model(request.user),
                    object_id=object_id,
                    changes={},
                )

                if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                    transaction.on_commit(
                        lambda: broadcast_admin_panel_refresh(
                            actor=request.user,
                            action_type=action_type,
                            path=request.path,
                            object_id=object_id,
                        )
                    )

            return response

        return wrapper

    return decorator
