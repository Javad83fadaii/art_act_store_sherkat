from .notification_messages import get_notification_catalog


def notification_messages(request):
    return {
        "notification_messages": get_notification_catalog(),
    }
