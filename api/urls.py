from django.urls import path
from myapp1.views import (
    csrf,
    LoginAPIView,
    RegisterUserAPIView,
    MyProfileAPIView,
    MemberListCreateAPIView,
    MemberRetrieveUpdateDestroyAPIView,
    AnnouncementListView,
    AnnouncementListCreateAPIView,
    AnnouncementRetrieveUpdateDestroyAPIView,
    PublicOpinionView,
)

urlpatterns = [
    path('csrf/', csrf, name='csrf'),  

    path('login/', LoginAPIView.as_view(), name='login'),
    path('register/', RegisterUserAPIView.as_view(), name='register'),

    path('my-profile/', MyProfileAPIView.as_view(), name='my-profile'),

    path('members/', MemberListCreateAPIView.as_view(), name='member-list-create'),
    path('members/<int:id>/', MemberRetrieveUpdateDestroyAPIView.as_view(), name='member-detail'),

    path('announcements/', AnnouncementListView.as_view(), name='announcement-list'),
    path('announcements/manage/', AnnouncementListCreateAPIView.as_view(), name='announcement-manage-list-create'),
    path('announcements/manage/<int:id>/', AnnouncementRetrieveUpdateDestroyAPIView.as_view(), name='announcement-manage-detail'),

    path('opinions/', PublicOpinionView.as_view(), name='opinion-list-create'),
    path('opinions/<int:pk>/', PublicOpinionView.as_view(), name='opinion-detail'),
]
