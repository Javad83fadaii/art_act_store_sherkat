# admin_panel_pages/urls.py

from django.urls import path
from .views import dashboard, products, reports, requests, settings, users, saved_filters

app_name = 'admin_panel_pages'

urlpatterns = [
    # Dashboard
    path('', dashboard.page_view, name='home'),
    path('dashboard/', dashboard.page_view, name='dashboard'),

    # Products
    path('products/create/', products.create_page_view, name='products-create'),
    path('products/store/', products.store_page_view, name='products-store'),
    path('products/store/<int:pk>/', products.store_detail_page_view, name='products-store-detail'),
    path('products/auctions/', products.auctions_page_view, name='products-auctions'),
    path('products/auctions/<int:pk>/', products.auction_detail_page_view, name='products-auctions-detail'),
    path('products/auction-products/', products.auction_products_page_view, name='products-auction-products'),
    path('products/auction-products/<int:pk>/', products.auction_product_detail_page_view, name='products-auction-products-detail'),
    path('products/reports/', products.reports_page_view, name='products-reports'),

    # Users
    path('users/', users.page_view, name='users'),
    path('users/login-history/', users.login_history_page_view, name='login-history'),
    path('users/<uuid:pk>/history/', users.history_page_view, name='user-history'),
    path('site-visits/', users.global_site_visits_page_view, name='site-visits'),

    # Saved Filters
    # نکته: در صورتی که نام تابع ویو در فایل saved_filters.py چیزی غیر از page_view است، آن را اصلاح کنید.
    path('saved-filters/', saved_filters.list_view, name='saved_filters_list'),


    # Requests / Settings
    path('requests/', requests.page_view, name='requests'),
    path('settings/', settings.page_view, name='settings'),
]
