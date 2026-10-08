from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EventCategoryViewSet,
    EventRegistrationViewSet,
    EventViewSet,
    PublicEventListView,
)

router = DefaultRouter()
router.register('events', EventViewSet, basename='event')
router.register('event-categories', EventCategoryViewSet, basename='event-category')
router.register('event-registrations', EventRegistrationViewSet, basename='event-registration')

urlpatterns = [
    # SRS 37 - public events of the website
    path('events/public/', PublicEventListView.as_view(), name='public-events'),
    path('', include(router.urls)),
]

