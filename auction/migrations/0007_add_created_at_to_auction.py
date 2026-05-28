from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0006_rebuild_bid_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='auction',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
    ]

