from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0022_alter_auctionproduct_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='auction',
            name='end_notice_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auction',
            name='end_reminder_12h_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auction',
            name='start_notice_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auction',
            name='start_reminder_24h_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auction',
            name='winner_billing_dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
