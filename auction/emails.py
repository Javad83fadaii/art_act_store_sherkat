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

    product = getattr(bid, "product", None)
    product_title = getattr(product, "title", "") or getattr(bid, "product_id", "")
    lot_number = getattr(product, "lot", "") or ""
    auction = getattr(product, "auction", None)
    auction_name = getattr(auction, "name", "") or ""

    subject = "ثبت پیشنهاد قیمت"
    message = (
        "با درود و احترام\n\n"
        f"پیشنهاد قیمت شما برای اثر {product_title} با موفقیت ثبت شد.\n"
        f"مبلغ پیشنهاد: {_format_amount(bid.bid_amount)}\n"
        f"شماره اثر: {lot_number}\n"
        f"مزایده: {auction_name}\n\n"
        "این پیشنهاد تا زمان ثبت پیشنهاد بالاتر، در رقابت معتبر خواهد بود.\n\n"
        "با احترام\n"
        "حراج هنری ماه\n"
        "Mahauction.com"
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
    subject = "خروج اثر از سبد مزایده"
    message = (
        "با درود و احترام\n\n"
        f"پیشنهاد بالاتری برای اثر {product_title} ثبت شده است و اثر از سبد مزایده شما خارج شده است.\n"
        "در صورت تمایل، می‌توانید با ثبت پیشنهاد جدید، مجدداً در رقابت این اثر شرکت کنید.\n\n"
        "با احترام\n"
        "حراج هنری ماه\n"
        "Mahauction.com"
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
                "با درود و احترام\n\n"
                f"تنها ۲۴ ساعت تا آغاز مزایده {auction_name} باقی مانده است.\n"
                "پیشنهاد می‌کنیم پیش از آغاز مزایده، آثار موردنظر خود را بررسی کرده و برای شرکت در رقابت آماده باشید.\n\n"
                "با احترام\n"
                "حراج هنری ماه\n"
                "Mahauction.com"
            ),
        )

    if reminder_type == "end_12h":
        return (
            f"یادآوری پایان مزایده «{auction_name}»",
            (
                "با درود و احترام\n\n"
                f"تنها ۱۲ ساعت تا پایان مزایده {auction_name} باقی مانده است.\n"
                "اگر اثر موردنظر خود را انتخاب کرده‌اید، فرصت ثبت یا افزایش پیشنهاد قیمت تا پایان مزایده همچنان برقرار است.\n\n"
                "با احترام\n"
                "حراج هنری ماه"
            ),
        )

    raise ValueError("Unknown auction reminder type.")
