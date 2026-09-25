from collections import OrderedDict
from decimal import Decimal, ROUND_CEILING

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from auction.models import AuctionCartItem, Bid, AuctionInvoice
from auction.services import (
    build_winner_access_token,
    ensure_products_have_finished_winners,
    create_or_get_invoice_for_winner,
)
from store.models import PurchaseHistory
from .forms import PublicProfileUpdateForm


def get_profile_group_name(user_id) -> str:
    return f'profile_user_{user_id}'


def build_profile_live_context(user) -> dict:
    user_model = get_user_model()
    live_user = user_model.objects.get(pk=user.pk)
    now = timezone.now()

    has_auction_opt_in = (
        int(getattr(live_user, 'is_verified', 0) or 0) == 1
        or live_user.has_pending_auction_request
    )

    bids = list(
        Bid.objects.filter(user=live_user)
        .select_related('product__artist', 'auction')
        .order_by('-created_at', '-pk')
    )
    ensure_products_have_finished_winners([bid.product for bid in bids])

    bid_groups = []
    group_map = {}
    for bid in bids:
        key = bid.product_id
        group = group_map.get(key)
        if group is None:
            group = {'product': bid.product, 'auction': bid.auction, 'bids': [], 'count': 0}
            group_map[key] = group
            bid_groups.append(group)
        group['bids'].append(bid)
        group['count'] += 1

    raw_auction_cart_items = list(
        AuctionCartItem.objects.filter(user=live_user)
        .select_related('product__artist', 'auction', 'bid')
        .order_by('-updated_at', '-created_at')
    )
    auction_cart_map = {}
    auction_cart_items = []
    for item in raw_auction_cart_items:
        key = item.product_id
        if key in auction_cart_map:
            continue
        auction_cart_map[key] = item
        bid_group = group_map.get(key)
        item.bid_history = bid_group['bids'] if bid_group else []
        item.bid_history_count = len(item.bid_history)
        auction_cart_items.append(item)

    current_auction_cart_items = [
        item for item in auction_cart_items
        if item.product.end_time >= now
    ]
    active_cart_items = [
        item for item in auction_cart_items
        if item.is_active and item.auction.start_date <= now <= item.product.end_time
    ]
    past_auction_cart_items = [
        item for item in auction_cart_items
        if item.product.end_time < now
    ]
    reserved_credit = sum(
        (item.reserved_amount for item in active_cart_items),
        start=Decimal('0'),
    )
    available_credit = live_user.calculate_current_credit()
    total_credit = Decimal(str(getattr(live_user, 'credit', 0) or 0))
    store_purchases = list(
        PurchaseHistory.objects.filter(user=live_user, artwork__is_sold__in=[1, 2])
        .select_related('artwork__artist')
        .order_by('-created_at', '-pk')
    )
    auction_purchases = [
        purchase for purchase in (
            live_user.won_auction_products
            .filter(
                Q(extended_end_time__isnull=False, extended_end_time__lt=now)
                | Q(extended_end_time__isnull=True, auction__end_date__lt=now)
            )
            .select_related('artist', 'auction')
            .order_by('-auction__end_date', '-pk')
        )
        if purchase.end_time < now and not purchase.is_in_extension and purchase.status == 'finished'
    ]
    for purchase in auction_purchases:
        purchase.detail_access_token = build_winner_access_token(
            user_id=live_user.pk,
            product_id=purchase.pk,
        )

    groups_map = OrderedDict()
    for purchase in auction_purchases:
        auction_obj = purchase.auction
        if auction_obj.pk not in groups_map:
            groups_map[auction_obj.pk] = {
                'auction': auction_obj,
                'items': [],
                'total_pure_price': Decimal('0'),
                'items_count': 0,
            }
        groups_map[auction_obj.pk]['items'].append(purchase)
        groups_map[auction_obj.pk]['total_pure_price'] += purchase.pure_price
        groups_map[auction_obj.pk]['items_count'] += 1

    auction_purchase_groups = []
    for auction_id, group in groups_map.items():
        auction_obj = group['auction']
        total_pure = group['total_pure_price']
        tax = (total_pure * Decimal('0.10')).to_integral_value(rounding=ROUND_CEILING)
        total_with_tax = total_pure + tax

        invoice = None
        if auction_obj.status == 'finished':
            invoice = AuctionInvoice.objects.filter(auction_id=auction_id, user=live_user).first()
            if not invoice:
                try:
                    invoice = create_or_get_invoice_for_winner(auction_obj, live_user, group['items'])
                except Exception:
                    invoice = None

        group['tax_amount'] = tax
        group['total_with_tax'] = total_with_tax
        group['invoice'] = invoice
        auction_purchase_groups.append(group)

    return {
        'user': live_user,
        'edit_form': PublicProfileUpdateForm(instance=live_user, has_auction_opt_in=has_auction_opt_in),
        'bids_total': len(bids),
        'bid_groups': bid_groups,
        'auction_cart_items': auction_cart_items,
        'current_auction_cart_items': current_auction_cart_items,
        'active_auction_cart_items': active_cart_items,
        'past_auction_cart_items': past_auction_cart_items,
        'auction_cart_total': len(auction_cart_items),
        'auction_cart_active_total': len(active_cart_items),
        'auction_reserved_credit': reserved_credit,
        'store_purchases': store_purchases,
        'auction_purchases': auction_purchases,
        'auction_purchase_groups': auction_purchase_groups,
        'live_credit': available_credit,
        'auction_total_credit': total_credit,
        'is_verified': int(getattr(live_user, 'is_verified', 0) or 0) == 1,
        'verification_pending': live_user.has_pending_auction_request,
    }


def build_profile_live_payload(user) -> dict:
    context = build_profile_live_context(user)
    return {
        'summary_html': render_to_string(
            'registration/partials/profile_auction_summary.html',
            context,
        ),
        'auction_cart_html': render_to_string(
            'registration/partials/profile_auction_cart.html',
            context,
        ),
        'purchases_html': render_to_string(
            'registration/partials/profile_purchase_sections.html',
            context,
        ),
        'bid_groups_html': render_to_string(
            'registration/partials/profile_bid_groups.html',
            context,
        ),
    }


def broadcast_profile_update(user_id) -> bool:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return False

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    async_to_sync(channel_layer.group_send)(
        get_profile_group_name(user_id),
        {
            'type': 'profile.auction.update',
            'user_id': str(user_id),
        },
    )
    return True
