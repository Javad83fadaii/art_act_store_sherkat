from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0002_refactor_auction_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auction',
            name='end_date',
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name='auction',
            name='start_date',
            field=models.DateTimeField(),
        ),
        migrations.AlterModelTable(
            name='auction',
            table='auction_auction',
        ),
    ]

