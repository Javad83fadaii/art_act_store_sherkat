from __future__ import annotations

from django.core import signing
from django.utils import timezone

from .models import AuctionProduct, Bid


def ensure_auction_product_winner(product: AuctionProduct) -> AuctionProduct:
    if product.auction.status != 'finished':
        return product

    latest_bid = (
        Bid.objects.filter(product_id=product.product_id)
        .select_related('user')
        .order_by('-created_at', '-pk')
        .first()
    )

    expected_winner_id = latest_bid.user_id if latest_bid is not None else None
    
    # قیمت نهایی شامل ۱۰ درصد مالیات و ارزش افزوده برای برنده
    if latest_bid is not None:
        raw_price = latest_bid.bid_amount
        # اضافه کردن ۱۰ درصد به قیمت
        from decimal import Decimal, ROUND_CEILING
        expected_price = (raw_price * Decimal('1.1')).to_integral_value(rounding=ROUND_CEILING)
        price_desc = "مبلغ آخرین پیشنهاد به علاوه ۱۰ درصد مالیات و ارزش افزوده"
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
