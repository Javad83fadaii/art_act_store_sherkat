from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("auction", "0018_remove_auctionproduct_bid_criteria"),
    ]

    operations = [
        migrations.AddField(
            model_name="auctionproduct",
            name="lot",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="لات"),
        ),
        migrations.AddConstraint(
            model_name="auctionproduct",
            constraint=models.UniqueConstraint(
                fields=("auction", "lot"),
                condition=models.Q(lot__isnull=False),
                name="uniq_auctionproduct_lot_per_auction",
            ),
        ),
    ]
