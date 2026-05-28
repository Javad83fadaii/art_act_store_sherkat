from django.db.models.signals import post_save, post_delete
from django.db import transaction
from django.dispatch import receiver

from .models import AuctionProduct, Bid, AuctionCartItem
from .realtime import broadcast_product_bid_update
from accounts.realtime import broadcast_profile_update


@receiver(post_save, sender=Bid)
def update_auction_product_current_price_on_bid_save(sender, instance: Bid, **kwargs):
    latest = (
        Bid.objects.filter(product_id=instance.product_id)
        .order_by('-created_at', '-pk')
        .values_list('bid_amount', flat=True)
        .first()
    )
    if latest is None:
        return
    product_pk = (
        AuctionProduct.objects
        .filter(product_id=instance.product_id)
        .values_list('pk', flat=True)
        .first()
    )
    AuctionProduct.objects.filter(product_id=instance.product_id).update(current_price=latest)
    if product_pk:
        transaction.on_commit(lambda: broadcast_product_bid_update(product_pk))
    
    # بروزرسانی پروفایل تمامی کاربرانی که روی این محصول بید زده‌اند
    user_ids = list(AuctionCartItem.objects.filter(product_id=instance.product_id).values_list('user_id', flat=True))
    
    def _broadcast_all():
        for uid in user_ids:
            broadcast_profile_update(uid)
            
    transaction.on_commit(_broadcast_all)


@receiver(post_delete, sender=Bid)
def on_bid_delete(sender, instance, **kwargs):
    # بروزرسانی پروفایل کاربر در صورت حذف بید
    transaction.on_commit(lambda: broadcast_profile_update(instance.user_id))


@receiver(post_save, sender=AuctionCartItem)
def on_cart_item_save(sender, instance, **kwargs):
    # بروزرسانی پروفایل کاربر در صورت تغییر در سبد خرید
    transaction.on_commit(lambda: broadcast_profile_update(instance.user_id))


@receiver(post_delete, sender=AuctionCartItem)
def on_cart_item_delete(sender, instance, **kwargs):
    # بروزرسانی پروفایل کاربر در صورت حذف از سبد خرید
    transaction.on_commit(lambda: broadcast_profile_update(instance.user_id))

