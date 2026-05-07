from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='auction',
            old_name='start_time',
            new_name='start_date',
        ),
        migrations.RenameField(
            model_name='auction',
            old_name='end_time',
            new_name='end_date',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='artist',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='authenticity_status',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='base_price',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='bid_type',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='condition_report',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='created_at',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='creation_year',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='current_price',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='description',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='dimensions',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='is_active',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='is_sold',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='medium',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='min_bid_fixed_amount',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='min_bid_percentage',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='price',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='product_id',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='provenance',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='title',
        ),
        migrations.RemoveField(
            model_name='auction',
            name='winner',
        ),
        migrations.AddField(
            model_name='auction',
            name='name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='auction',
            name='products_count',
            field=models.PositiveIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name='auction',
            options={'ordering': ['-start_date'], 'verbose_name': 'Auction', 'verbose_name_plural': 'Auctions'},
        ),
    ]
