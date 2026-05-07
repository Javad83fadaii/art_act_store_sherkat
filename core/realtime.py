from django.utils import timezone


def broadcast_admin_notification(notification_type, title, message, data=None, timestamp=None):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return False

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    async_to_sync(channel_layer.group_send)(
        'admin_notifications',
        {
            'type': 'notification',
            'notification_type': notification_type,
            'title': title,
            'message': message,
            'data': data or {},
            'timestamp': (timestamp or timezone.now()).isoformat(),
        }
    )
    return True


def broadcast_admin_panel_refresh(reason='update', meta=None):
    return broadcast_admin_notification(
        notification_type='admin_panel_refresh',
        title='بروزرسانی پنل',
        message=f'بروزرسانی: {reason}',
        data={'reason': reason, 'meta': meta or {}}
    )
