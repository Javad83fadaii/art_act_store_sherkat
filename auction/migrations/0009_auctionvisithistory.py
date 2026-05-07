from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0008_alter_auctionproduct_authenticity_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuctionVisitHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='آدرس IP')),
                ('timestamp', models.DateTimeField(auto_now_add=True, verbose_name='زمان بازدید')),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='visit_history', to='auction.auction', verbose_name='مزایده')),
                ('product', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='visit_history', to='auction.auctionproduct', verbose_name='محصول مزایده')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auction_visit_history', to=settings.AUTH_USER_MODEL, verbose_name='کاربر')),
            ],
            options={
                'verbose_name': 'تاریخچه بازدید مزایده',
                'verbose_name_plural': 'تاریخچه بازدیدهای مزایده',
                'db_table': 'auction_visit_history',
                'ordering': ['-timestamp'],
            },
        ),
    ]
