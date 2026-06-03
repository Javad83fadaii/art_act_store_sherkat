# admin_panel/views/saved_filters.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from core.models import SavedFilter
from core.notification_messages import get_notification
from core.decorators import superuser_required
import json

@superuser_required
def list_view(request):
    """نمایش لیست فیلترهای ذخیره شده"""
    saved_filters = SavedFilter.objects.filter(user=request.user)
    
    context = {
        'saved_filters': saved_filters,
    }
    return render(request, 'admin_panel/saved_filters.html', context)

@superuser_required
def create_view(request):
    """ایجاد فیلتر جدید"""
    if request.method != 'POST':
        return redirect('admin_panel:saved_filters')
    
    name = request.POST.get('name')
    page = request.POST.get('page')
    is_default = request.POST.get('is_default') == 'true'
    
    if not name or not page:
        messages.error(request, get_notification('admin.saved_filters.name_page_required'))
        return redirect('admin_panel:saved_filters')
    
    # ساخت دیکشنری فیلترها
    filters = {}
    
    if page == 'users':
        if request.POST.get('status'):
            filters['status'] = request.POST.get('status')
        if request.POST.get('date_joined__gte'):
            filters['date_joined__gte'] = request.POST.get('date_joined__gte')
        if request.POST.get('date_joined__lte'):
            filters['date_joined__lte'] = request.POST.get('date_joined__lte')
        if request.POST.get('is_staff'):
            filters['is_staff'] = True
        if request.POST.get('exclude_staff'):
            filters['is_staff'] = False
            
    elif page == 'orders':
        if request.POST.get('order_status'):
            filters['status'] = request.POST.get('order_status')
        if request.POST.get('created_at__gte'):
            filters['created_at__gte'] = request.POST.get('created_at__gte')
        if request.POST.get('created_at__lte'):
            filters['created_at__lte'] = request.POST.get('created_at__lte')
    
    if not filters:
        messages.error(request, get_notification('admin.saved_filters.at_least_one_filter'))
        return redirect('admin_panel:saved_filters')
    
    # اگر default باشه، بقیه رو غیرفعال کن
    if is_default:
        SavedFilter.objects.filter(user=request.user, page=page).update(is_default=False)
    
    # ذخیره فیلتر
    SavedFilter.objects.create(
        user=request.user,
        page=page,
        name=name,
        filters=filters,
        is_default=is_default
    )
    
    messages.success(request, get_notification('admin.saved_filters.created', name=name))
    return redirect('admin_panel:saved_filters')

@superuser_required
def delete_view(request, filter_id):
    """حذف فیلتر"""
    if request.method != 'POST':
        return redirect('admin_panel:saved_filters')
    
    saved_filter = get_object_or_404(SavedFilter, id=filter_id, user=request.user)
    name = saved_filter.name
    saved_filter.delete()
    
    messages.success(request, get_notification('admin.saved_filters.deleted', name=name))
    return redirect('admin_panel:saved_filters')

@superuser_required
def set_default_view(request, filter_id):
    """تنظیم فیلتر به عنوان پیش‌فرض"""
    if request.method != 'POST':
        return redirect('admin_panel:saved_filters')
    
    saved_filter = get_object_or_404(SavedFilter, id=filter_id, user=request.user)
    
    # غیرفعال کردن بقیه فیلترهای default
    SavedFilter.objects.filter(user=request.user, page=saved_filter.page).update(is_default=False)
    
    # فعال کردن این فیلتر
    saved_filter.is_default = True
    saved_filter.save()
    
    messages.success(request, get_notification('admin.saved_filters.set_default', name=saved_filter.name))
    return redirect('admin_panel:saved_filters')

@superuser_required
def apply_view(request, filter_id):
    """اعمال فیلتر و هدایت به صفحه مربوطه"""
    saved_filter = get_object_or_404(SavedFilter, id=filter_id, user=request.user)
    
    # ساخت URL با پارامترهای فیلتر
    if saved_filter.page == 'users':
        url = reverse('admin_panel:users')
    elif saved_filter.page == 'orders':
        url = reverse('admin_panel:orders')
    else:
        messages.error(request, get_notification('admin.saved_filters.invalid_page'))
        return redirect('admin_panel:saved_filters')
    
    # اضافه کردن پارامترها به URL
    params = []
    for key, value in saved_filter.filters.items():
        params.append(f'{key}={value}')
    
    if params:
        url += '?' + '&'.join(params)
    
    return redirect(url)
