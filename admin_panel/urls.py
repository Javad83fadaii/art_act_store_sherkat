# admin_panel/urls.py
from django.urls import path

from .views import dashboard, products, reports, requests, settings, users, saved_filters

app_name = 'admin_panel'

urlpatterns = [
    # ==========================
    # Dashboard
    # ==========================
    path('dashboard/stats/', dashboard.stats_view, name='dashboard-stats'),
    path('dashboard/charts/', dashboard.charts_view, name='dashboard-charts'),
    path('dashboard/activities/', dashboard.activities_view, name='dashboard-activities'),
    path('dashboard/orders/', dashboard.orders_view, name='dashboard-orders'),
    path('dashboard/ending-auctions/', dashboard.ending_auctions_view, name='dashboard-ending-auctions'),
    path('dashboard/new-users/', dashboard.new_users_view, name='dashboard-new-users'),
    
    # ==========================
    # Products (Store & Auction)
    # ==========================
    # Store Products
    path('products/store/', products.store_list, name='products-store-list'),
    path('products/store/stats/', products.store_stats, name='products-store-stats'),
    path('products/store/bulk/', products.store_bulk, name='products-store-bulk'),
    path('products/store/<int:pk>/', products.store_detail, name='products-store-detail'),
    path('products/options/', products.product_options, name='products-options'),
    path('products/reports/visits/', products.visit_reports, name='products-visit-reports'),
    
    # Auctions (Main Management)
    path('products/auctions-main/', products.auction_main_list, name='products-auction-main-list'),
    path('products/auctions-main/<int:pk>/', products.auction_main_detail, name='products-auction-main-detail'),
    
    # Auction Products (Items inside auctions)
    path('products/auction/', products.auction_list, name='products-auction-list'),
    path('products/auction/stats/', products.auction_stats, name='products-auction-stats'),
    path('products/auction/bulk/', products.auction_bulk, name='products-auction-bulk'),
    path('products/auction/<int:pk>/', products.auction_detail, name='products-auction-detail'),
    
    # Bids
    path('products/reports/bids/', products.bid_reports, name='products-bid-reports'),
    path('products/auction/<int:pk>/bids/', products.product_bids, name='products-auction-bids'),
    
    # ==========================
    # Requests
    # ==========================
    path('notifications/', requests.notifications_feed, name='notifications-feed'),
    path('requests/', requests.list_view, name='requests-list'),
    path('requests/<str:request_type>/<int:pk>/', requests.detail_view, name='requests-detail'),
    path('requests/bulk/', requests.bulk_action, name='requests-bulk'),
    path('requests/templates/', requests.templates_list, name='requests-templates'),
    
    # ==========================
    # Users
    # ==========================
    path('users/', users.list_view, name='users-list'),
    path('users/<uuid:pk>/', users.detail_view, name='users-detail'),
    path('users/bulk/', users.bulk_action, name='users-bulk'),
    path('users/<uuid:pk>/auction-activity/', users.auction_activity, name='users-auction-activity'),
    path('users/<uuid:pk>/history-api/', users.history_api_view, name='users-history-api'),
    path('users/login-history-api/', users.login_history_api_view, name='users-login-history-api'),
    path('users/site-visits-api/', users.global_site_visits_api_view, name='api-site-visits'),
    path('users/<uuid:pk>/bids/', users.user_bids_api, name='user-bids-api'),
    path('users/<uuid:pk>/product-visits-api/', users.user_product_visits_api, name='user-product-visits-api'),
    path('users/<uuid:pk>/cart-bids-summary/', users.user_cart_bids_summary_api, name='user-cart-bids-summary-api'),
    path('users/<uuid:pk>/purchased-products/', users.user_purchased_products_api, name='user-purchased-products-api'),
    path('users/<uuid:pk>/purchase-requests-summary/', users.user_purchase_requests_summary_api, name='user-purchase-requests-summary-api'),
    path('users/<uuid:pk>/reserved-products/', users.user_reserved_products_api, name='user-reserved-products-api'),
    path('users/<uuid:pk>/telegram-requests/', users.user_telegram_requests_api, name='user-telegram-requests-api'),
    
    # ==========================
    # Saved Filters
    # ==========================
    path('saved-filters/', saved_filters.list_view, name='saved-filters'),
    path('saved-filters/create/', saved_filters.create_view, name='saved-filters-create'),
    path('saved-filters/<int:filter_id>/delete/', saved_filters.delete_view, name='saved-filters-delete'),
    path('saved-filters/<int:filter_id>/set-default/', saved_filters.set_default_view, name='saved-filters-set-default'),
    path('saved-filters/<int:filter_id>/apply/', saved_filters.apply_view, name='saved-filters-apply'),
    
    # ==========================
    # Reports
    # ==========================
    path('reports/activity-logs/', reports.activity_logs, name='reports-activity-logs'),
    path('reports/error-logs/', reports.error_logs, name='reports-error-logs'),
    path('reports/error-logs/<int:pk>/', reports.resolve_error, name='reports-resolve-error'),
    path('reports/admin-logs/', reports.admin_logs, name='reports-admin-logs'),
    path('reports/auction-visit-logs/', reports.auction_visit_logs, name='reports-auction-visit-logs'),
    path('reports/export/', reports.export_data, name='reports-export'),
    
    # ==========================
    # Settings
    # ==========================
    path('settings/', settings.get_settings, name='settings-get'),
    path('settings/notifications/', settings.notifications, name='settings-notifications'),
    path('filters/', settings.filters_list, name='settings-filters'),
    path('filters/<int:pk>/', settings.filter_detail, name='settings-filter-detail'),
    path('filters/<int:pk>/default/', settings.set_default_filter, name='settings-filter-default'),
]
