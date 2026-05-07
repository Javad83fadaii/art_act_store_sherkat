from decimal import Decimal, InvalidOperation, ROUND_CEILING

from django.template.loader import render_to_string

from .models import AuctionProduct, Bid
from .services import ensure_auction_product_winner


def get_auction_product_group_name(product_pk: int) -> str:
    return f'auction_product_{product_pk}'


def _as_int_price(value) -> int:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal('0')
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def _build_my_bids_context(product: AuctionProduct, user) -> tuple[list[Bid], int]:
    if not getattr(user, 'is_authenticated', False):
        return [], 0

    user_bids_qs = Bid.objects.filter(user=user, product_id=product.product_id)
    my_bids = list(user_bids_qs.order_by('-created_at', '-pk')[:50])
    my_bids_count = user_bids_qs.count()

    highest_auction_bid = (
        Bid.objects.filter(product_id=product.product_id)
        .order_by('-bid_amount')
        .values_list('bid_amount', flat=True)
        .first()
    )
    highest_user_bid = (
        user_bids_qs.order_by('-bid_amount')
        .values_list('bid_amount', flat=True)
        .first()
    )
    latest_user_bid_id = (
        user_bids_qs.order_by('-created_at', '-pk')
        .values_list('id', flat=True)
        .first()
    )

    for bid in my_bids:
        bid.is_latest = bid.id == latest_user_bid_id
        bid.is_user_top = highest_user_bid and bid.bid_amount == highest_user_bid
        bid.is_user_highest = (
            bool(highest_user_bid)
            and bool(highest_auction_bid)
            and highest_user_bid == highest_auction_bid
            and bid.bid_amount == highest_user_bid
        )

    return my_bids, my_bids_count


def build_bid_live_payload(product: AuctionProduct | int, user=None) -> dict:
    if isinstance(product, int):
        product = (
            AuctionProduct.objects.select_related('auction', 'winner')
            .get(pk=product)
        )
    else:
        product = (
            AuctionProduct.objects.select_related('auction', 'winner')
            .get(pk=product.pk)
        )

    product = ensure_auction_product_winner(product)
    my_bids, my_bids_count = _build_my_bids_context(product, user)

    return {
        'current_price': _as_int_price(product.current_price or product.base_price),
        'bid_count': product.bids.count(),
        'min_next_bid': product.get_min_next_bid(),
        'has_winner': bool(product.winner_id),
        'my_bids_count': my_bids_count,
        'my_bids_html': render_to_string(
            'auction/partials/my_bid_history.html',
            {
                'my_bids': my_bids,
                'my_bids_count': my_bids_count,
                'user': user,
            },
        ),
    }


def broadcast_product_bid_update(product_pk: int) -> bool:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return False

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    async_to_sync(channel_layer.group_send)(
        get_auction_product_group_name(product_pk),
        {
            'type': 'auction.bid.update',
            'product_pk': product_pk,
        },
    )
    return True
