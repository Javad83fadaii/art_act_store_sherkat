from decimal import Decimal

from django import template

from auction.models import Bid
from auction.ranking import get_top_unique_bid_amounts

register = template.Library()

@register.filter
def get_bid_rank(bid):
    """
    Returns the rank (1..10 or None) of a bid among unique bid amounts for its product.
    """
    if not bid or not bid.product_id:
        return None
        
    top_amounts = get_top_unique_bid_amounts(bid.product_id, limit=10)
    
    try:
        rank = top_amounts.index(Decimal(str(bid.bid_amount))) + 1
        return rank
    except ValueError:
        return None

@register.simple_tag
def get_user_product_rank(user, product):
    """
    Returns the rank (1..10 or None) of the user's highest bid for a product.
    """
    if not user or not product or not user.is_authenticated:
        return None
        
    product_id = getattr(product, 'product_id', product)
    
    top_amounts = get_top_unique_bid_amounts(product_id, limit=10)
    
    # Get user's highest bid for this product
    user_highest = Bid.objects.filter(user=user, product_id=product_id).order_by('-bid_amount').first()
    
    if not user_highest:
        return None
        
    try:
        rank = top_amounts.index(Decimal(str(user_highest.bid_amount))) + 1
        return rank
    except ValueError:
        return None
