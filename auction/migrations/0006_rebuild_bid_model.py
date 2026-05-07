import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0005_create_suggested_price'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='Bid',
        ),
        migrations.CreateModel(
            name='Bid',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bid_amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('user_fullname', models.CharField(max_length=255)),
                ('user_mobile', models.CharField(max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bids', to='auction.auction')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bids', to='auction.auctionproduct', to_field='product_id')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auction_bids', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'auction_bid',
                'ordering': ['-created_at'],
            },
        ),
    ]

