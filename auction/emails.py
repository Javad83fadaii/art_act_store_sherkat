from decimal import Decimal, InvalidOperation

from core.emailing import send_plain_email


def _format_amount(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return f"{int(amount):,}"


def send_bid_confirmation_email(*, bid):
    user = getattr(bid, "user", None)
    if not user or not getattr(user, "email", None):
        return 0

    product_title = getattr(getattr(bid, "product", None), "title", "") or getattr(bid, "product_id", "")
    display_name = (getattr(user, "get_full_name", lambda: "")() or getattr(user, "full_name", "") or "کاربر گرامی")
    subject = "پیشنهاد شما ثبت شد"
    message = (
        f"{display_name} عزیز،\n\n"
        f"پیشنهاد شما به مبلغ {_format_amount(bid.bid_amount)} تومان برای اثر «{product_title}» با موفقیت ثبت شد.\n"
        "تا زمانی که بالاترین پیشنهاد را داشته باشید، این اثر در سبد مزایده شما فعال می‌ماند.\n\n"
        "با آرزوی موفقیت."
    )
    return send_plain_email(
        event='auction.bid.confirmed',
        subject=subject,
        message=message,
        recipients=[user.email],
        fail_silently=True,
        metadata={'bid_id': str(bid.pk)},
    )


def send_outbid_email(*, previous_bid, latest_bid):
    previous_user = getattr(previous_bid, "user", None)
    if not previous_user or not getattr(previous_user, "email", None):
        return 0

    product_title = getattr(getattr(latest_bid, "product", None), "title", "") or getattr(latest_bid, "product_id", "")
    display_name = (
        getattr(previous_user, "get_full_name", lambda: "")()
        or getattr(previous_user, "full_name", "")
        or "کاربر گرامی"
    )
    subject = "محصول از سبد مزایده شما خارج شد"
    message = (
        f"{display_name} عزیز،\n\n"
        f"کاربر دیگری برای اثر «{product_title}» پیشنهاد بالاتری ثبت کرده است.\n"
        "به همین دلیل این اثر از سبد مزایده فعال شما خارج شد.\n"
        f"پیشنهاد جدید ثبت‌شده: {_format_amount(latest_bid.bid_amount)} تومان\n\n"
        "اگر همچنان مایل هستید، می‌توانید دوباره پیشنهاد جدید ثبت کنید."
    )
    return send_plain_email(
        event='auction.bid.outbid',
        subject=subject,
        message=message,
        recipients=[previous_user.email],
        fail_silently=True,
        metadata={
            'previous_bid_id': str(previous_bid.pk),
            'latest_bid_id': str(latest_bid.pk),
        },
    )


def build_auction_reminder_email(*, auction, reminder_type):
    auction_name = getattr(auction, "name", "") or f"مزایده {auction.pk}"

    if reminder_type == "start_24h":
        return (
            f"یادآوری شروع مزایده «{auction_name}»",
            (
                "سلام,\n\n"
                f"مزایده «{auction_name}» تا ۲۴ ساعت دیگر آغاز می‌شود.\n"
                "اگر قصد شرکت دارید، از قبل حساب کاربری و موجودی خود را بررسی کنید.\n\n"
                "با آرزوی موفقیت."
            ),
        )

    if reminder_type == "end_12h":
        return (
            f"یادآوری پایان مزایده «{auction_name}»",
            (
                "سلام,\n\n"
                f"تنها ۱۲ ساعت تا پایان مزایده «{auction_name}» باقی مانده است.\n"
                "اگر روی آثار این مزایده پیشنهاد فعال دارید، وضعیت آن‌ها را دوباره بررسی کنید.\n\n"
                "با آرزوی موفقیت."
            ),
        )

    raise ValueError("Unknown auction reminder type.")
