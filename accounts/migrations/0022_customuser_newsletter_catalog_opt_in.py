from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0021_remove_customuser_first_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="newsletter_catalog_opt_in",
            field=models.BooleanField(
                default=False,
                verbose_name="تمایل به دریافت خبرنامه و کاتالوگ",
            ),
        ),
    ]