from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='کاربر')
    action = models.CharField(max_length=255, verbose_name='عملیات')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='زمان')
    details = models.TextField(blank=True, verbose_name='جزئیات')

    class Meta:
        verbose_name = 'گزارش فعالیت'
        verbose_name_plural = 'گزارش‌های فعالیت'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"


class AdminActivityLog(models.Model):
    admin_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='کاربر مدیر')
    action = models.CharField(max_length=100, verbose_name='نوع عملیات')
    description = models.TextField(blank=True, verbose_name='شرح عملیات')
    target_type = models.CharField(max_length=100, blank=True, null=True, verbose_name='نوع هدف')
    target_id = models.CharField(max_length=255, blank=True, null=True, verbose_name='شناسه هدف')
    target_repr = models.CharField(max_length=255, blank=True, null=True, verbose_name='عنوان هدف')
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='نوع مدل')
    object_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='شناسه عددی مدل')
    changes = models.JSONField(default=dict, blank=True, verbose_name='تغییرات')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='آدرس IP')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='زمان ثبت')

    class Meta:
        verbose_name = 'لاگ فعالیت ادمین'
        verbose_name_plural = 'لاگ‌های فعالیت ادمین‌ها'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['admin_user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['target_type', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.admin_user} - {self.action} - {self.timestamp}"


class ErrorLog(models.Model):
    ERROR_TYPES = [
        ('500', 'Internal Server Error'),
        ('404', 'Not Found'),
        ('403', 'Forbidden'),
        ('400', 'Bad Request'),
    ]

    error_type = models.CharField(max_length=3, choices=ERROR_TYPES)
    url = models.CharField(max_length=500)
    method = models.CharField(max_length=10)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    stack_trace = models.TextField()
    request_data = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['error_type', 'timestamp']),
            models.Index(fields=['resolved', 'timestamp']),
        ]


class SavedFilter(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    page = models.CharField(max_length=50)
    filters = models.JSONField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'page', 'name')]


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    new_user_panel = models.BooleanField(default=True)
    new_user_email = models.BooleanField(default=False)
    new_user_telegram = models.BooleanField(default=False)
    new_request_panel = models.BooleanField(default=True)
    new_request_email = models.BooleanField(default=False)
    new_request_telegram = models.BooleanField(default=False)
    new_bid_panel = models.BooleanField(default=True)
    new_bid_email = models.BooleanField(default=False)
    new_purchase_panel = models.BooleanField(default=True)
    new_purchase_email = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class TemplateMessage(models.Model):
    CATEGORY_CHOICES = [
        ('verification_reject', 'Verification Reject'),
        ('credit_reject', 'Credit Reject'),
        ('purchase_reject', 'Purchase Reject'),
        ('general', 'General'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    content = models.TextField()
    variables = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-usage_count', '-created_at']
