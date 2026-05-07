from django.contrib import admin

from .models import Auction, AuctionVisitHistory, Bid


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'start_date',
        'end_date',
        'products_count',
        'status',
    )
    search_fields = ('name',)
    list_filter = ('start_date', 'end_date')
    ordering = ('-start_date',)
    
    fieldsets = (
        (None, {'fields': ('name', 'start_date', 'end_date', 'products_count')}),
    )


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('auction', 'product', 'user', 'bid_amount', 'created_at')
    list_select_related = ('auction', 'product', 'user')
    search_fields = ("auction__name", "product__product_id", "product__title", "user__phone_number", "user__full_name")
    list_filter = ('created_at',)


@admin.register(AuctionVisitHistory)
class AuctionVisitHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'auction', 'product', 'timestamp')
    list_select_related = ('user', 'auction', 'product')
    readonly_fields = ('user', 'ip_address', 'auction', 'product', 'timestamp')
    search_fields = ('auction__name', 'product__title', 'ip_address', 'user__phone_number', 'user__full_name')
    list_filter = ('timestamp', 'auction')
