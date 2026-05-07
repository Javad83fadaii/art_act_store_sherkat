from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    # نمایش لیست آثار هنری
    path('', views.ArtworkListView.as_view(), name='artwork_list'),

    # نمایش جزئیات هر اثر هنری
    path('artwork/<int:pk>/', views.ArtworkDetailView.as_view(), name='artwork_detail'),

    # لایک محصول
    path('artwork/<int:pk>/like/', views.ToggleLikeView.as_view(), name='toggle_like'),

    # جستجو
    path('search/', views.search_artworks, name='search_artworks'),

    # ثبت سفارش و رزرو (API)
    path('artwork/<int:pk>/reserve/', views.reserve_artwork, name='reserve_artwork'),
    path('telegram/purchase-webhook/', views.telegram_purchase_webhook, name='telegram_purchase_webhook'),
]
