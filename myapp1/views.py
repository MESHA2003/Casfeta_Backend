from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, mixins, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import viewsets


from .models import Member, Announcement, PublicOpinion,Leaderboard
from .serializers import (
    MemberSerializer,
    RegisterSerializer,
    AnnouncementSerializer,
    PublicOpinionSerializer,
    LeaderboardSerializer
)


# ------------------ CSRF Utility ------------------

@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({'detail': 'CSRF cookie set'})


# ------------------ Login ------------------

class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)

        if user:
            return Response({
                "message": "Login successful",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email
                }
            }, status=status.HTTP_200_OK)
        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)


# ------------------ Register ------------------

class RegisterUserAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User registered successfully!"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------ Member Profile ------------------

class MyProfileAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"detail": "No user registered with this email."}, status=404)

        if Member.objects.filter(email__iexact=email).exists():
            return Response({"detail": "A profile with this email already exists."}, status=400)

        serializer = MemberSerializer(data=request.data, context={'user': user})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    def put(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"detail": "Email is required."}, status=400)

        try:
            member = Member.objects.get(email__iexact=email)
        except Member.DoesNotExist:
            return Response({"detail": "Profile not found."}, status=404)

        serializer = MemberSerializer(member, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def get(self, request):
        email = request.query_params.get('email')
        if not email:
            return Response({"detail": "Email query parameter is required."}, status=400)

        try:
            member = Member.objects.get(email__iexact=email)
            serializer = MemberSerializer(member)
            return Response(serializer.data, status=200)
        except Member.DoesNotExist:
            return Response({"detail": "Profile not found."}, status=404)


# ------------------ Member Admin APIs ------------------

class MemberListCreateAPIView(generics.ListCreateAPIView):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    permission_classes = [IsAdminUser]


class MemberRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    lookup_field = 'id'
    permission_classes = [IsAdminUser]


# ------------------ Announcements ------------------

class AnnouncementListView(generics.ListAPIView):
    queryset = Announcement.objects.all().order_by('-created_at')
    serializer_class = AnnouncementSerializer
    permission_classes = [AllowAny]


class AnnouncementListCreateAPIView(generics.ListCreateAPIView):
    queryset = Announcement.objects.all().order_by('-created_at')
    serializer_class = AnnouncementSerializer
    permission_classes = [IsAdminUser]


class AnnouncementRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    lookup_field = 'id'
    permission_classes = [IsAdminUser]


# ------------------ Public Opinion ------------------

class PublicOpinionView(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView
):
    queryset = PublicOpinion.objects.all().order_by('-created_at')
    serializer_class = PublicOpinionSerializer
    permission_classes = [AllowAny]

    def get(self, request, pk=None):
        if pk:
            return self.retrieve(request, pk=pk)
        return self.list(request)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    def put(self, request, pk=None):
        return self.update(request, pk=pk)

    def patch(self, request, pk=None):
        return self.partial_update(request, pk=pk)

    def delete(self, request, pk=None):
        return self.destroy(request, pk=pk)


class leaderBoardView(viewsets.ModelViewSet):
    queryset = Leaderboard.objects.all()
    serializer_class = LeaderboardSerializer

    
