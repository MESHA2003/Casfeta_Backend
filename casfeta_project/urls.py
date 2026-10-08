"""
URL configuration for the CASFETA Zanzibar Digital Management & Ministry
Platform (CZDMP).

Every platform endpoint lives under ``/api/`` exactly as documented in the SRS
(section 54). The legacy CASFETA endpoints (login, register, my-profile,
opinions, csrf) keep answering on their original paths for backwards
compatibility, and the whole legacy URLconf stays reachable under
``/api/legacy/``. Where legacy and platform share a path (``members/`` and
``announcements/``) the platform API is canonical.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""


from django.conf import settings
from django.conf.urls.static import static

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- CZDMP platform API (SRS 54) ---------------------------------------
    path('api/', include('core.urls')),
    path('api/', include('accounts.urls')),
    path('api/', include('audit.urls')),
    path('api/', include('branches.urls')),
    path('api/', include('members.urls')),
    path('api/', include('leadership.urls')),
    path('api/', include('ministries.urls')),
    path('api/', include('events.urls')),
    path('api/', include('attendance.urls')),
    path('api/finance/', include('finance.urls')),
    path('api/', include('reports.urls')),
    path('api/', include('notifications.urls')),
    path('api/', include('resources.urls')),
    path('api/', include('prayer.urls')),
    path('api/', include('testimonies.urls')),
    path('api/', include('certificates.urls')),
    
    # --- Legacy CASFETA endpoints (backwards compatibility) -----------------
    path('api/', include('api.urls')),
    path('api/legacy/', include('api.urls')),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
