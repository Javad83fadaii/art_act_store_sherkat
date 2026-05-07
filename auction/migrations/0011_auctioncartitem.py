from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0010_auction_updated_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuctionCartItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reserved_amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cart_items', to='auction.auction')),
                ('bid', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='cart_item', to='auction.bid')),
                ('product', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='cart_item', to='auction.auctionproduct', to_field='product_id')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auction_cart_items', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'auction_cart_item',
                'ordering': ['-updated_at', '-created_at'],
            },
        ),
    ]
