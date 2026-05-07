import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0003_alter_auction_end_date_alter_auction_start_date_and_more'),
        ('store', '0006_remove_purchasehistory_action_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuctionProduct',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_id', models.CharField(max_length=64, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('authenticity_status', models.SmallIntegerField(choices=[(0, 'verified'), (1, 'not verified')], default=0)),
                ('description', models.TextField(blank=True, null=True)),
                ('dimensions', models.CharField(blank=True, max_length=255, null=True)),
                ('creation_year', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('base_price', models.DecimalField(decimal_places=2, max_digits=15)),
                ('current_price', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('bid_criteria', models.SmallIntegerField(choices=[(0, 'percentage-based'), (1, 'fixed-amount')], default=0)),
                ('bid_value', models.DecimalField(decimal_places=2, max_digits=15)),
                ('suggested_price', models.DecimalField(decimal_places=2, max_digits=15, null=True)),
                ('artist', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='auction_products', to='store.artist')),
                ('artwork_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='auction_products', to='store.artworktype')),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='products', to='auction.auction')),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='won_auction_products', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'auction_product',
                'ordering': ['-created_at'],
            },
        ),
    ]
