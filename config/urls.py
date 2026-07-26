from django.urls import path, include, re_path
from core import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('39556468.txt', views.enamad_verification_file, name='enamad_verification_file'),
    path('accounts/', include('accounts.urls')), 
    path('accounts/', include('django.contrib.auth.urls')),
    path('track-visit/', views.track_public_visit, name='track_public_visit'),
    
    # API endpoints
    path('api/admin/', include(('admin_panel.urls', 'admin_panel'), namespace='admin_panel')),
    
    # صفحات HTML پنل ادمین
    path('admin-panel/', include(('admin_panel.page_urls', 'admin_panel_pages'), namespace='admin_panel_pages')),
    
    path('store/', include('store.urls')),
    path('auction/', include('auction.urls')),
    path('about/', views.about, name='about'),
    path('site_rules/', views.site_rules, name='site_rules'),
    re_path(r'^static/images/(?P<subpath>.*\.(?:mp4|webm|mov|m4v))$', views.static_video, name='static_video'),
    path('', views.home, name='home')
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    try:
        urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    except (AttributeError, IndexError):
        print("Warning: STATICFILES_DIRS not found in settings.py")
