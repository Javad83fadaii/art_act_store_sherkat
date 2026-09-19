from __future__ import annotations

from django.db import models

from notifications.enums import NotificationChannel, NotificationProviderType, NotificationStatus


class StoredNotificationTemplate(models.Model):
    """Persisted notification template for future integrations."""

    key = models.CharField(max_length=100)
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices())
    subject_template = models.CharField(max_length=255, blank=True)
    body_template = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key', 'channel']
        unique_together = [('key', 'channel')]
        verbose_name = 'Notification template'
        verbose_name_plural = 'Notification templates'

    def __str__(self) -> str:
        return f'{self.key} ({self.channel})'


class NotificationDelivery(models.Model):
    """Audit trail for notification dispatch attempts."""

    event = models.CharField(max_length=100)
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices())
    provider = models.CharField(max_length=20, choices=NotificationProviderType.choices())
    recipients = models.JSONField(default=list)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices(),
        default=NotificationStatus.PENDING,
    )
    detail = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['channel', 'provider']),
        ]
        verbose_name = 'Notification delivery'
        verbose_name_plural = 'Notification deliveries'

    def __str__(self) -> str:
        return f'{self.event} - {self.provider} - {self.status}'
