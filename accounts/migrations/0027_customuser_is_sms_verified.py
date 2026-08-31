from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0026_smsverificationotp"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="is_sms_verified",
            field=models.BooleanField(default=True),
        ),
    ]
