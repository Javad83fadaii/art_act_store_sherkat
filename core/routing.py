from django.urls import path

from core.consumers import AdminNotificationConsumer
from accounts.consumers import ProfileAuctionStateConsumer
from auction.consumers import AuctionPageRefreshConsumer, AuctionProductBidConsumer

websocket_urlpatterns = [
    path('ws/admin/notifications/', AdminNotificationConsumer.as_asgi()),
    path('ws/profile/auction-state/', ProfileAuctionStateConsumer.as_asgi()),
    path('ws/auction/<int:auction_pk>/page/', AuctionPageRefreshConsumer.as_asgi()),
    path('ws/auction/product/<int:product_pk>/', AuctionProductBidConsumer.as_asgi()),
]
