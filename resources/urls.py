from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NewsArticleViewSet, ResourceCategoryViewSet, ResourceViewSet

router = DefaultRouter()
router.register('resources', ResourceViewSet, basename='resource')
router.register('resource-categories', ResourceCategoryViewSet, basename='resource-category')
router.register('news', NewsArticleViewSet, basename='news-article')

urlpatterns = [
    # SRS 32, 37, 43, 67 - library, categories and news
    path('', include(router.urls)),
]

