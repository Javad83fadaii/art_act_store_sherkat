from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from notifications.services import send_notification_safely


def normalize_email_value(value):
    return str(value or "").strip().lower()


def collect_valid_recipient_emails(recipients):
    cleaned_recipients = []

    for raw_email in recipients or []:
        email = normalize_email_value(raw_email)
        if not email:
            continue
        validate_email(email)
        cleaned_recipients.append(email)

    unique_recipients = list(dict.fromkeys(cleaned_recipients))
    if not unique_recipients:
        raise ValidationError("حداقل یک آدرس ایمیل معتبر لازم است.")

    return unique_recipients


def send_plain_email(
    *,
    subject,
    message,
    recipients,
    fail_silently=False,
    event='email.message',
    metadata=None,
    context=None,
):
    valid_recipients = collect_valid_recipient_emails(recipients)
    send_notification_safely(
        event=str(event or 'email.message').strip(),
        recipients=valid_recipients,
        subject=str(subject or "").strip(),
        body=str(message or "").strip(),
        context=context,
        metadata={
            'fail_silently': bool(fail_silently),
            'from_email': settings.DEFAULT_FROM_EMAIL,
            **(metadata or {}),
        },
    )
    return len(valid_recipients)


def get_user_email_recipients(*, queryset=None, only_active=True, only_verified_email=False):
    user_model = get_user_model()
    users = queryset if queryset is not None else user_model.objects.all()

    if only_active:
        users = users.filter(is_active=True)

    users = users.exclude(email__isnull=True).exclude(email__exact="")

    if only_verified_email:
        users = users.filter(is_email_verified=True)

    return list(
        dict.fromkeys(
            normalize_email_value(email)
            for email in users.values_list("email", flat=True)
            if normalize_email_value(email)
        )
    )
