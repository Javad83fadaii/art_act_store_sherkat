from django.contrib import admin

from notifications.models import NotificationDelivery, StoredNotificationTemplate


@admin.register(StoredNotificationTemplate)
class StoredNotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('key', 'channel', 'is_active', 'updated_at')
    list_filter = ('channel', 'is_active')
    search_fields = ('key', 'subject_template', 'body_template')
    ordering = ('key', 'channel')


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ('event', 'provider', 'channel', 'status', 'created_at')
    list_filter = ('provider', 'channel', 'status', 'created_at')
    search_fields = ('event', 'subject', 'body', 'detail')
    readonly_fields = (
        'event',
        'channel',
        'provider',
        'recipients',
        'subject',
        'body',
        'status',
        'detail',
        'metadata',
        'created_at',
    )
    ordering = ('-created_at',)
