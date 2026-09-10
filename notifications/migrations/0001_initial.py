from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='StoredNotificationTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100)),
                ('channel', models.CharField(choices=[('email', 'Email'), ('sms', 'Sms'), ('telegram', 'Telegram')], max_length=20)),
                ('subject_template', models.CharField(blank=True, max_length=255)),
                ('body_template', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Notification template',
                'verbose_name_plural': 'Notification templates',
                'ordering': ['key', 'channel'],
                'unique_together': {('key', 'channel')},
            },
        ),
        migrations.CreateModel(
            name='NotificationDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(max_length=100)),
                ('channel', models.CharField(choices=[('email', 'Email'), ('sms', 'Sms'), ('telegram', 'Telegram')], max_length=20)),
                ('provider', models.CharField(choices=[('email', 'Email'), ('sms', 'Sms'), ('telegram', 'Telegram')], max_length=20)),
                ('recipients', models.JSONField(default=list)),
                ('subject', models.CharField(blank=True, max_length=255)),
                ('body', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='pending', max_length=20)),
                ('detail', models.TextField(blank=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Notification delivery',
                'verbose_name_plural': 'Notification deliveries',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notificationdelivery',
            index=models.Index(fields=['event', 'created_at'], name='notificatio_event_c3f320_idx'),
        ),
        migrations.AddIndex(
            model_name='notificationdelivery',
            index=models.Index(fields=['status', 'created_at'], name='notificatio_status_1e9b53_idx'),
        ),
        migrations.AddIndex(
            model_name='notificationdelivery',
            index=models.Index(fields=['channel', 'provider'], name='notificatio_channel_1824f3_idx'),
        ),
    ]
