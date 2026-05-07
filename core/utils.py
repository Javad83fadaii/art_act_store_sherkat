import hashlib
import json
from datetime import datetime, timezone
from functools import wraps

from django.core.cache import cache


def _should_bypass_cache(request) -> bool:
    bypass_header = request.headers.get('X-Admin-Bypass-Cache', '')
    cache_control = request.headers.get('Cache-Control', '')
    pragma = request.headers.get('Pragma', '')
    return (
        request.GET.get('nocache') is not None
        or request.GET.get('_ts') is not None
        or bypass_header == '1'
        or 'no-cache' in cache_control.lower()
        or 'no-cache' in pragma.lower()
    )


def cache_response(timeout=300, key_prefix=''):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if _should_bypass_cache(request):
                return view_func(request, *args, **kwargs)

            payload = {
                'path': request.path,
                'query': dict(request.GET),
                'kwargs': kwargs,
            }
            hashed_payload = hashlib.md5(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest()
            cache_key = f'{key_prefix}:{hashed_payload}'
            cached = cache.get(cache_key)

            if cached is not None:
                return cached

            response = view_func(request, *args, **kwargs)
            if getattr(response, 'status_code', 500) == 200:
                cache.set(cache_key, response, timeout)
            return response

        return wrapper

    return decorator


def invalidate_cache(key_pattern):
    if hasattr(cache, 'delete_pattern'):
        return cache.delete_pattern(key_pattern)

    if hasattr(cache, 'keys'):
        keys = cache.keys(key_pattern)
        if keys:
            return cache.delete_many(keys)

    return 0


try:
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
except ImportError:
    async_to_sync = None
    get_channel_layer = None


def send_admin_notification(notification_type, title, message, data=None, timestamp=None):
    if async_to_sync is None or get_channel_layer is None:
        return False

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        'type': 'notification',
        'notification_type': str(notification_type or 'general'),
        'title': str(title or ''),
        'message': str(message or ''),
        'data': data or {},
        'timestamp': timestamp,
    }

    async_to_sync(channel_layer.group_send)('admin_notifications', payload)
    return True


def broadcast_admin_panel_refresh(*, actor=None, action_type='', path='', object_id=None):
    actor_label = ''
    if actor is not None:
        actor_label = (
            getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or 'ادمین'
        )

    title = 'بروزرسانی زنده پنل'
    message = f'تغییری توسط {actor_label} در پنل مدیریت ثبت شد.' if actor_label else 'تغییری در پنل مدیریت ثبت شد.'
    data = {
        'action_type': str(action_type or ''),
        'path': str(path or ''),
        'object_id': object_id,
    }
    return send_admin_notification(
        'admin_panel_refresh',
        title,
        message,
        data=data,
    )
