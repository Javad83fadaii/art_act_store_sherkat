from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0012_artwork_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegrampurchaserequest',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='زمان بروزرسانی',
            ),
            preserve_default=False,
        ),
    ]
