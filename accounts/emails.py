from core.emailing import send_plain_email


def send_verification_code_email(*, email, code):
    subject = "کد تایید ایمیل شما"
    message = (
        "سلام,\n\n"
        f"کد تایید ۶ رقمی شما: {code}\n"
        "این کد تا ۱۰ دقیقه معتبر است.\n\n"
        "اگر این درخواست را شما ثبت نکرده‌اید، این پیام را نادیده بگیرید."
    )
    return send_plain_email(
        event='accounts.signup.verification_code',
        subject=subject,
        message=message,
        recipients=[email],
        fail_silently=False,
        metadata={'code': str(code)},
    )


def send_welcome_email(*, user):
    if not getattr(user, "email", None):
        return 0

    display_name = (
        getattr(user, "get_full_name", lambda: "")() or getattr(user, "full_name", "") or "کاربر گرامی"
    )
    subject = "خوش آمدید"
    message = (
        f"{display_name} عزیز،\n\n"
        "ثبت نام شما در سایت با موفقیت انجام شد.\n"
        "برای استفاده کامل از امکانات سایت، لطفا ایمیل خود را با کد ارسالی تایید کنید.\n\n"
        "از همراهی شما خوشحالیم."
    )
    return send_plain_email(
        event='accounts.signup.welcome',
        subject=subject,
        message=message,
        recipients=[user.email],
        fail_silently=False,
        metadata={'user_id': str(user.pk)},
    )
