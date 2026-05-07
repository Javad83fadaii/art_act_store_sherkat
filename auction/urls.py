from django.urls import path
from . import views

app_name = 'auction'

urlpatterns = [
    path('', views.AuctionListView.as_view(), name='auction'),
    path('action/', views.AuctionListView.as_view(), name='action'),
    path('grid/', views.AuctionGridView.as_view(), name='auction_grid'),
    path('<int:pk>/products/', views.AuctionProductsView.as_view(), name='auction_products'),
    path('product/<int:pk>/', views.auction_product_detail, name='auction_product_detail'),
    path('<int:pk>/', views.AuctionDetailView.as_view(), name='auction_detail'),
    path('product/<int:pk>/bid/', views.place_bid, name='place_bid'),
    path('product/<int:pk>/live-state/', views.auction_product_live_state, name='auction_product_live_state'),
    path('<int:pk>/bid/', views.place_bid, name='place_bid_legacy'),
    
    # مسیر جدید اضافه شده برای ثبت درخواست افزایش اعتبار از طریق پنجره پاپ‌آپ (AJAX)
    path('ajax/request-credit-increase/', views.submit_credit_increase_ajax, name='submit_credit_increase_ajax'),
]
