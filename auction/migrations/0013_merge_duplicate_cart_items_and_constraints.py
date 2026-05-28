from django.db import migrations, models
from django.utils import timezone


def merge_duplicate_cart_items(apps, schema_editor):
    AuctionCartItem = apps.get_model('auction', 'AuctionCartItem')

    cart_items = list(
        AuctionCartItem.objects.all().order_by('user_id', 'product_id', '-updated_at', '-created_at', '-pk')
    )

    seen_user_product = {}
    duplicate_ids = []

    for item in cart_items:
        key = (item.user_id, item.product_id)
        if key in seen_user_product:
            duplicate_ids.append(item.pk)
            continue
        seen_user_product[key] = item

    if duplicate_ids:
        AuctionCartItem.objects.filter(pk__in=duplicate_ids).delete()

    active_items = list(
        AuctionCartItem.objects.filter(is_active=True).order_by('product_id', '-updated_at', '-created_at', '-pk')
    )
    seen_active_product = {}
    deactivate_ids = []

    for item in active_items:
        if item.product_id in seen_active_product:
            deactivate_ids.append(item.pk)
            continue
        seen_active_product[item.product_id] = item.pk

    if deactivate_ids:
        AuctionCartItem.objects.filter(pk__in=deactivate_ids).update(
            is_active=False,
            outbid_at=timezone.now(),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0012_auctioncartitem_is_active_auctioncartitem_outbid_at_and_more'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_cart_items, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='auctioncartitem',
            constraint=models.UniqueConstraint(
                fields=('user', 'product'),
                name='uniq_auction_cart_item_user_product',
            ),
        ),
    ]
