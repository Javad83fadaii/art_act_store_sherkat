from notifications.enums import NotificationProviderType
from notifications.services import notification_service


def _resolve_display_name(user) -> str:
    display_name = (
        getattr(user, "get_full_name", lambda: "")() or getattr(user, "full_name", "") or ""
    )
    display_name = str(display_name).strip()
    return display_name or "کاربر"


def send_verification_code_email(*, email, code, user=None):
    subject = "کد تایید ایمیل شما"
    message = (
        "سلام,\n\n"
        f"کد تایید ۶ رقمی شما: {code}\n"
        "این کد تا ۱۰ دقیقه معتبر است.\n\n"
        "اگر این درخواست را شما ثبت نکرده‌اید، این پیام را نادیده بگیرید."
    )

    email_result = notification_service.send(
        event='accounts.signup.verification_code',
        subject=subject,
        body=message,
        recipients=[email],
        providers=[NotificationProviderType.EMAIL],
        context={'user': user} if user is not None else {},
        metadata={'code': str(code)},
    )

    return email_result


def send_verification_code_sms(*, user, code):
    return notification_service.send_template(
        event='accounts.signup.verification_code',
        template_key='verification',
        providers=[NotificationProviderType.SMS],
        user=user,
        context={
            'code': str(code),
        },
        metadata={
            'code': str(code),
            'user_id': str(user.pk),
        },
    )


def send_welcome_email(*, user):
    if not getattr(user, "email", None):
        return 0

    display_name = _resolve_display_name(user)
    subject = "خوش آمدید"
    message = (
        f"{display_name} عزیز،\n\n"
        "ثبت نام شما در سایت با موفقیت انجام شد.\n"
        "برای استفاده کامل از امکانات سایت، لطفا ایمیل خود را با کد ارسالی تایید کنید.\n\n"
        "از همراهی شما خوشحالیم."
    )
    return notification_service.send(
        event='accounts.signup.welcome',
        subject=subject,
        body=message,
        recipients=[user.email],
        providers=[NotificationProviderType.EMAIL],
        context={'user': user},
        metadata={
            'user_id': str(user.pk),
        },
    )


def send_welcome_sms(*, user):
    if not getattr(user, "phone_number", None):
        return 0

    return notification_service.send_template(
        event='accounts.signup.welcome_sms',
        template_key='signup_welcome',
        providers=[NotificationProviderType.SMS],
        user=user,
        context={
            'NAME': _resolve_display_name(user),
        },
        metadata={
            'user_id': str(user.pk),
        },
    )
