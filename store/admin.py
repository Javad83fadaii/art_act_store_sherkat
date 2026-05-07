from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import TelegramPurchaseRequest, Artwork, PurchaseHistory
from django.utils import timezone
from .models import (
    Artist, Artwork, ProductLike, VisitHistory, 
    TelegramPurchaseRequest, PurchaseHistory, SiteVisitLog
)

# --- مدیریت لاگ حضور کاربران ---
@admin.register(SiteVisitLog)
class SiteVisitLogAdmin(admin.ModelAdmin):
    list_display = ('session_key', 'user', 'ip_address', 'start_time', 'last_activity', 'get_duration')
    list_filter = ('start_time', 'user')
    search_fields = ('session_key', 'ip_address', 'user__username')
    readonly_fields = ('start_time', 'last_activity', 'session_key', 'ip_address', 'user')

    def get_duration(self, obj):
        return f"{obj.duration_in_minutes()} دقیقه"
    get_duration.short_description = "مدت حضور"


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ('name', 'bio')
    search_fields = ('name',)


@admin.register(Artwork)
class ArtworkAdmin(admin.ModelAdmin):
    list_display = ('product_id', 'title', 'artist', 'price', 'is_sold', 'image_preview_small')
    list_select_related = ('artist',)
    search_fields = ('title', 'artist__name', 'product_id')
    list_filter = ('is_sold', 'created_at', 'artist')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('اطلاعات اصلی', {'fields': ('title', 'artist', 'product_id')}),
        ('توضیحات و قیمت', {'fields': ('description', 'price')}),
        ('وضعیت فروش', {'fields': ('is_sold', 'authenticity_status')}),
        ('تصویر', {'fields': ('image_preview',)}),
    )
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if hasattr(obj, 'main_image_url') and obj.main_image_url:
            return mark_safe(f'<img src="{obj.main_image_url}" style="max-height: 200px; border-radius: 10px;" />')
        return "بدون تصویر"

    def image_preview_small(self, obj):
        if hasattr(obj, 'main_image_url') and obj.main_image_url:
            return mark_safe(f'<img src="{obj.main_image_url}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 5px;" />')
        return "---"
    image_preview_small.short_description = "عکس"

@admin.register(TelegramPurchaseRequest)
class TelegramPurchaseRequestAdmin(admin.ModelAdmin):
    # ۱. فیلد status را حتما به list_display اضافه کردیم تا list_editable کار کند
    list_display = ('id', 'user', 'artwork', 'status', 'status_colored', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'artwork__title')
    
    # ۲. فیلد اصلی status حالا قابل ویرایش سریع است
    list_editable = ('status',)
    readonly_fields = ('created_at', 'token')

    def status_colored(self, obj):
        colors = {
            'pending': 'orange', 
            'confirmed': 'green', 
            'rejected': 'red', 
            'contacted': 'blue'
        }
        color = colors.get(obj.status, "black")
        return mark_safe(f'<b style="color: {color};">{obj.get_status_display()}</b>')
    status_colored.short_description = "نمای وضعیت"

    def save_model(self, request, obj, form, change):
        """هنگام تغییر وضعیت به تایید شده، اثر هنری فروخته شده و ادمین ثبت می‌شود"""
        
        # ابتدا ذخیره اصلی انجام شود
        super().save_model(request, obj, form, change)
        
        # بررسی تغییر وضعیت به 'confirmed'
        if change and 'status' in form.changed_data and obj.status == 'confirmed':
            # ۱. تغییر وضعیت اثر به فروخته شده (SOLD)
            artwork = obj.artwork
            artwork.is_sold = Artwork.IsSoldStatus.SOLD
            artwork.save()

            # ۲. به‌روزرسانی تاریخچه خرید با نام ادمین تایید کننده
            # استفاده از update برای بهینه‌سازی و اطمینان از اعمال روی تمام رکوردهای مرتبط این کاربر و اثر
            PurchaseHistory.objects.filter(
                user=obj.user, 
                artwork=obj.artwork
            ).update(confirmed_by=request.user)

# @admin.register(PurchaseHistory)
# class PurchaseHistoryAdmin(admin.ModelAdmin):
#     list_display = ('id', 'artwork_title', 'purchased_price', 'user', 'confirmed_by', 'created_at')
#     list_filter = ('created_at', 'confirmed_by')
#     search_fields = ('artwork_title', 'product_id', 'user__username', 'buyer_phone')
#     # فیلد قیمت و ادمین تایید کننده را فقط خواندنی کردیم تا سوابق دستکاری نشود
#     readonly_fields = ('user', 'artwork', 'artwork_title', 'product_id', 'purchased_price', 'buyer_phone', 'confirmed_by', 'created_at')
    
#     def has_add_permission(self, request): return False # سوابق خرید نباید دستی اضافه شوند


@admin.register(VisitHistory)
class VisitHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'timestamp')
    readonly_fields = ('user', 'product', 'timestamp')


@admin.register(ProductLike)
class ProductLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    autocomplete_fields = ['user', 'product']
