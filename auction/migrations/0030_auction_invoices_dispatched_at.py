from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0029_remove_invoice_status_and_artist_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='auction',
            name='invoices_dispatched_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='زمان صدور فاکتورها'),
        ),
    ]
