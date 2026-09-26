from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING
from django.core import signing
from django.utils import timezone

from .models import AuctionProduct, Bid


# جدول پله‌های افزایش قیمت مزایده (به تومان)
# مبالغ تا سقف هر پله مشمول افزایش همان پله هستند و با رسیدن به سقف وارد پله بعدی می‌شوند
TIERED_BID_INCREMENTS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal('50000000'), Decimal('5000000')),      # تا سقف ۵۰,۰۰۰,۰۰۰ تومان: ۵,۰۰۰,۰۰۰
    (Decimal('200000000'), Decimal('10000000')),    # از ۵۰,۰۰۰,۰۰۰ تا ۲۰۰,۰۰۰,۰۰۰ تومان: ۱۰,۰۰۰,۰۰۰
    (Decimal('500000000'), Decimal('20000000')),    # از ۲۰۰,۰۰۰,۰۰۰ تا ۵۰۰,۰۰۰,۰۰۰ تومان: ۲۰,۰۰۰,۰۰۰
    (Decimal('1000000000'), Decimal('50000000')),   # از ۵۰۰,۰۰۰,۰۰۰ تا ۱,۰۰۰,۰۰۰,۰۰۰ تومان: ۵۰,۰۰۰,۰۰۰
    (Decimal('4000000000'), Decimal('100000000')),  # از ۱,۰۰۰,۰۰۰,۰۰۰ تا ۴,۰۰۰,۰۰۰,۰۰۰ تومان: ۱۰۰,۰۰۰,۰۰۰
)
TOP_TIER_INCREMENT = Decimal('200000000')           # از ۴,۰۰۰,۰۰۰,۰۰۰ تومان به بالا: ۲۰۰,۰۰۰,۰۰۰


def get_current_step_increment(price: Decimal | int | float | str | None) -> int:
    """محاسبه میزان افزایش گام بر اساس جدول پله‌ای و قیمت جاری اثر (به تومان)"""
    try:
        current = Decimal(str(price or 0))
    except (InvalidOperation, TypeError, ValueError):
        current = Decimal('0')
    if current < Decimal('0'):
        current = Decimal('0')

    for upper_limit, increment in TIERED_BID_INCREMENTS:
        if current < upper_limit:
            return int(increment)
    return int(TOP_TIER_INCREMENT)


def get_min_next_bid(current_or_base_price: Decimal | int | float | str | None) -> int:
    """محاسبه حداقل مبلغ پیشنهاد بعدی (خالص) بر اساس قیمت فعلی اثر به علاوه افزایش پله جاری"""
    try:
        current = Decimal(str(current_or_base_price or 0))
    except (InvalidOperation, TypeError, ValueError):
        current = Decimal('0')
    if current < Decimal('0'):
        current = Decimal('0')

    step = Decimal(str(get_current_step_increment(current)))
    return int((current + step).to_integral_value(rounding=ROUND_CEILING))


def ensure_auction_product_winner(product: AuctionProduct) -> AuctionProduct:
    now = timezone.now()
    if now < product.end_time:
        return product

    latest_bid = (
        Bid.objects.filter(product_id=product.product_id)
        .select_related('user')
        .order_by('-created_at', '-pk')
        .first()
    )

    expected_winner_id = latest_bid.user_id if latest_bid is not None else None
    
    # مبلغ خالص فروش بر اساس آخرین پیشنهاد (بدون افزودن مالیات به فیلد current_price)
    if latest_bid is not None:
        expected_price = latest_bid.bid_amount
        price_desc = None
    else:
        expected_price = product.current_price or product.base_price
        price_desc = None

    if (product.winner_id == expected_winner_id and 
        product.current_price == expected_price and 
        product.price_description == price_desc):
        return product

    previous_winner_id = product.winner_id
    AuctionProduct.objects.filter(pk=product.pk).update(
        winner_id=expected_winner_id,
        current_price=expected_price,
        price_description=price_desc,
        updated_at=timezone.now(),
    )

    product.winner_id = expected_winner_id
    product.current_price = expected_price
    product.price_description = price_desc
    product.winner = latest_bid.user if latest_bid is not None else None

    # بروزرسانی Artwork مرتبط در صورت وجود
    if expected_winner_id:
        try:
            from store.models import Artwork
            Artwork.objects.filter(product_id=product.product_id).update(
                price=expected_price,
                price_description=price_desc,
                is_sold=1, # SOLD status
                updated_at=timezone.now(),
            )
        except ImportError:
            pass

    from accounts.realtime import broadcast_profile_update
    from .realtime import broadcast_product_bid_update

    impacted_user_ids = {
        user_id
        for user_id in (previous_winner_id, expected_winner_id)
        if user_id
    }
    for user_id in impacted_user_ids:
        broadcast_profile_update(user_id)

    broadcast_product_bid_update(product.pk)
    return product


def ensure_products_have_finished_winners(products) -> list[AuctionProduct]:
    normalized_products: list[AuctionProduct] = []
    seen_product_ids: set[int] = set()

    for product in products or []:
        if product is None or product.pk in seen_product_ids:
            continue
        seen_product_ids.add(product.pk)
        normalized_products.append(product)

    for product in normalized_products:
        ensure_auction_product_winner(product)

    return normalized_products


def build_winner_access_token(*, user_id: int, product_id: int) -> str:
    return signing.dumps(
        {
            'purpose': 'auction_winner_access',
            'user_id': int(user_id),
            'product_id': int(product_id),
        },
        salt='auction.winner-access',
    )


def has_valid_winner_access_token(*, token: str, user_id: int, product_id: int) -> bool:
    if not token:
        return False

    try:
        payload = signing.loads(token, salt='auction.winner-access', max_age=60 * 60 * 24 * 30)
    except signing.BadSignature:
        return False
    except signing.SignatureExpired:
        return False

    return (
        payload.get('purpose') == 'auction_winner_access'
        and int(payload.get('user_id') or 0) == int(user_id)
        and int(payload.get('product_id') or 0) == int(product_id)
    )


def generate_invoice_number(issued_at=None) -> str:
    """
    شماره فاکتور ۹ رقمی شمسی: SSSDDMMYY
    - SSS: شماره ترتیبی فاکتور (۰۰۱، ۰۰۲، ...)
    - DD: روز صدور شمسی
    - MM: ماه صدور شمسی
    - YY: دو رقم آخر سال شمسی
    مثال: اولین فاکتور در ۵ مهر ۱۴۰۵ → 001050705
    """
    from .models import AuctionInvoice
    import jdatetime
    import re

    now = issued_at or timezone.now()
    loc_now = timezone.localtime(now)
    try:
        j_dt = jdatetime.datetime.fromgregorian(datetime=loc_now)
        j_day = j_dt.day
        j_month = j_dt.month
        j_year_2 = j_dt.year % 100
    except Exception:
        j_day = loc_now.day
        j_month = loc_now.month
        j_year_2 = loc_now.year % 100

    date_suffix = f"{j_day:02d}{j_month:02d}{j_year_2:02d}"

    next_seq = 1
    for inv_number in AuctionInvoice.objects.values_list('invoice_number', flat=True):
        if inv_number and re.fullmatch(r'\d{9}', inv_number):
            try:
                seq = int(inv_number[:3])
                if seq >= next_seq:
                    next_seq = seq + 1
            except ValueError:
                continue

    while next_seq <= 999:
        candidate = f"{next_seq:03d}{date_suffix}"
        if not AuctionInvoice.objects.filter(invoice_number=candidate).exists():
            return candidate
        next_seq += 1

    raise ValueError('سقف شماره ترتیبی فاکتور (۹۹۹) پر شده است.')


def create_or_get_invoice_for_winner(auction, user, products=None):
    """
    ایجاد یا دریافت فاکتور رسمی برنده مزایده پس از پایان قطعی مزایده
    """
    from django.db import transaction
    from .models import AuctionInvoice, AuctionInvoiceItem

    if auction.status != 'finished':
        return None

    existing = AuctionInvoice.objects.filter(auction=auction, user=user).first()
    if existing:
        return existing

    if products is None:
        products = list(
            auction.products.filter(winner=user)
            .order_by('lot', 'pk')
        )
    else:
        products = [p for p in products if p.winner_id == user.pk]

    if not products:
        return None

    with transaction.atomic():
        existing = AuctionInvoice.objects.filter(auction=auction, user=user).first()
        if existing:
            return existing

        total_hammer = Decimal('0')
        invoice_items_data = []

        for product in products:
            hammer_price = product.pure_price
            premium = (hammer_price * Decimal('0.10')).to_integral_value(rounding=ROUND_CEILING)
            total_item_price = hammer_price + premium
            total_hammer += hammer_price

            invoice_items_data.append({
                'product': product,
                'lot': product.lot,
                'product_code': product.product_id,
                'title': product.title,
                'hammer_price': hammer_price,
                'buyers_premium': premium,
                'total_price': total_item_price,
            })

        buyers_premium = (total_hammer * Decimal('0.10')).to_integral_value(rounding=ROUND_CEILING)
        total_amount = total_hammer + buyers_premium
        issued_at = timezone.now()
        inv_number = generate_invoice_number(issued_at=issued_at)

        invoice = AuctionInvoice.objects.create(
            invoice_number=inv_number,
            auction=auction,
            user=user,
            issued_at=issued_at,
            total_hammer_price=total_hammer,
            buyers_premium=buyers_premium,
            total_amount=total_amount,
        )

        for item_data in invoice_items_data:
            AuctionInvoiceItem.objects.create(
                invoice=invoice,
                **item_data
            )

        return invoice


def generate_invoices_for_auction(auction, products=None) -> list:
    """
    صدور خودکار فاکتور برای تمام برندگان مزایده پس از پایان قطعی آن
    """
    if auction.status != 'finished':
        return []

    if products is None:
        products = list(auction.products.select_related('winner').all())

    ensure_products_have_finished_winners(products)

    from collections import defaultdict
    winners_products = defaultdict(list)
    for product in products:
        if product.winner:
            winners_products[product.winner].append(product)

    invoices = []
    for winner, user_products in winners_products.items():
        invoice = create_or_get_invoice_for_winner(auction, winner, user_products)
        if invoice:
            invoices.append(invoice)

    return invoices

