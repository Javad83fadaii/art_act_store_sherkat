from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from auction.models import Bid


def _normalize_amount(value) -> Decimal:
    return Decimal(str(value or 0))


def get_top_unique_bid_amounts(product_id, limit: int = 3) -> list[Decimal]:
    if not product_id or limit <= 0:
        return []

    amounts: list[Decimal] = []
    seen: set[Decimal] = set()

    queryset = (
        Bid.objects.filter(product_id=product_id)
        .order_by('-bid_amount', 'created_at', 'pk')
        .values_list('bid_amount', flat=True)
    )

    for amount in queryset:
        normalized = _normalize_amount(amount)
        if normalized in seen:
            continue
        seen.add(normalized)
        amounts.append(normalized)
        if len(amounts) >= limit:
            break

    return amounts


def get_product_rankings(product_ids, limit: int = 3) -> dict[str, list[dict]]:
    normalized_product_ids = [str(product_id) for product_id in product_ids if product_id]
    if not normalized_product_ids or limit <= 0:
        return {}

    user_best_bids: dict[str, dict[int, dict]] = defaultdict(dict)

    queryset = (
        Bid.objects.filter(product_id__in=normalized_product_ids)
        .order_by('product_id', '-bid_amount', 'created_at', 'pk')
        .values(
            'product_id',
            'user_id',
            'user_fullname',
            'user_mobile',
            'bid_amount',
            'created_at',
        )
    )

    for row in queryset:
        product_id = str(row['product_id'])
        user_id = row['user_id']
        if user_id in user_best_bids[product_id]:
            continue
        user_best_bids[product_id][user_id] = row

    rankings: dict[str, list[dict]] = {}

    for product_id, users_map in user_best_bids.items():
        best_bids = list(users_map.values())
        best_bids.sort(
            key=lambda item: (
                -_normalize_amount(item['bid_amount']),
                item['created_at'] or 0,
                item['user_fullname'] or '',
            )
        )

        product_ranks: list[dict] = []
        ranked_amounts: list[Decimal] = []

        for item in best_bids:
            amount = _normalize_amount(item['bid_amount'])
            if amount not in ranked_amounts:
                if len(ranked_amounts) >= limit:
                    break
                ranked_amounts.append(amount)

            rank = ranked_amounts.index(amount) + 1
            product_ranks.append(
                {
                    'rank': rank,
                    'user_id': item['user_id'],
                    'user_fullname': item['user_fullname'] or 'کاربر نامشخص',
                    'user_mobile': item['user_mobile'] or '-',
                    'bid_amount': str(amount),
                    'created_at': item['created_at'].isoformat() if item['created_at'] else None,
                }
            )

        rankings[product_id] = product_ranks

    return rankings
