from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Auction, AuctionVisitHistory, Bid, AuctionInvoice, AuctionInvoiceItem


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


class AuctionInvoiceItemInline(admin.TabularInline):
    model = AuctionInvoiceItem
    extra = 0
    readonly_fields = ('lot', 'product_code', 'title', 'artist_name', 'hammer_price', 'buyers_premium', 'total_price')
    can_delete = False


@admin.register(AuctionInvoice)
class AuctionInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number',
        'auction',
        'user',
        'total_hammer_price',
        'buyers_premium',
        'total_amount',
        'status',
        'issued_at',
        'download_pdf_button',
    )
    list_filter = ('status', 'auction', 'issued_at')
    search_fields = ('invoice_number', 'user__full_name', 'user__phone_number', 'auction__name')
    ordering = ('-issued_at', '-id')
    inlines = [AuctionInvoiceItemInline]
    readonly_fields = (
        'invoice_number',
        'auction',
        'user',
        'issued_at',
        'total_hammer_price',
        'buyers_premium',
        'total_amount',
        'created_at',
        'updated_at',
    )

    def download_pdf_button(self, obj):
        url = reverse('auction:invoice_pdf', args=[obj.pk])
        return format_html('<a class="button" href="{}" target="_blank">دانلود PDF</a>', url)
    download_pdf_button.short_description = 'دانلود فاکتور'

