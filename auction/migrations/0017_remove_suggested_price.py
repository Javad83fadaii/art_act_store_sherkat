from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0016_auctionproduct_price_description'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='auctionproduct',
            name='suggested_price',
        ),
        migrations.DeleteModel(
            name='SuggestedPrice',
        ),
    ]
