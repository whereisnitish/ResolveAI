from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import lockout, services
from apps.accounts.models import UserManager
from apps.accounts.serializers import (
    EmailSerializer,
    LoginSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    RegisterSerializer,
    TokenSerializer,
    UserSerializer,
    build_me_payload,
)
from apps.audit import services as audit
from apps.audit.services import AuditAction
from common.authentication import CsrfProtectedAPIViewMixin
from common.exceptions import ServiceError

DetailSerializer = inline_serializer("Detail", {"detail": serializers.CharField()})


class _AuthThrottled(CsrfProtectedAPIViewMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class CsrfView(APIView):
    """Issue the CSRF cookie. The SPA calls this once before any unsafe request."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: inline_serializer("Csrf", {"csrf_token": serializers.CharField()})})
    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request)})


class RegisterView(_AuthThrottled):
    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses={201: MeSerializer})
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.register_user(
            email=data["email"],
            password=data["password"],
            full_name=data["full_name"],
            organization_name=(data.get("organization_name") or "").strip() or None,
            country=data.get("country", ""),
            invitation_token=data.get("invitation_token") or None,
            request=request,
        )
        login(request, result.user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(MeSerializer(build_me_payload(result.user)).data, status=status.HTTP_201_CREATED)


class LoginView(_AuthThrottled):
    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer})
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = UserManager.normalize_email_address(serializer.validated_data["email"])
        if lockout.is_locked(email):
            audit.record(AuditAction.USER_LOGIN_FAILED, request=request, metadata={"email": email, "locked": True})
            raise ServiceError(
                "Too many failed sign-in attempts. Try again later or reset your password.",
                code="login_locked",
                status_code=429,
            )
        user = authenticate(request, username=email, password=serializer.validated_data["password"])
        if user is None:
            lockout.register_failure(email)
            audit.record(AuditAction.USER_LOGIN_FAILED, request=request, metadata={"email": email})
            raise ServiceError("Invalid email or password.", code="invalid_credentials", status_code=400)
        lockout.reset(email)
        login(request, user)  # rotates the session key (prevents fixation)
        audit.record(AuditAction.USER_LOGIN, actor=user, request=request, target=user)
        return Response(MeSerializer(build_me_payload(user)).data)


class LogoutView(CsrfProtectedAPIViewMixin, APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        if request.user.is_authenticated:
            audit.record(AuditAction.USER_LOGOUT, actor=request.user, request=request, target=request.user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeSerializer})
    def get(self, request: Request) -> Response:
        return Response(MeSerializer(build_me_payload(request.user)).data)

    @extend_schema(request=UserSerializer, responses={200: UserSerializer})
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class VerifyEmailView(_AuthThrottled):
    permission_classes = [AllowAny]

    @extend_schema(request=TokenSerializer, responses={200: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.verify_email(serializer.validated_data["token"], request=request)
        return Response({"detail": "Email verified."})


class ResendVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_sensitive"

    @extend_schema(request=None, responses={202: DetailSerializer})
    def post(self, request: Request) -> Response:
        if not request.user.is_email_verified:
            services.send_verification_email(request.user)
        return Response({"detail": "If your email is unverified, a new link has been sent."}, status=202)


class PasswordResetRequestView(CsrfProtectedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_sensitive"

    @extend_schema(request=EmailSerializer, responses={202: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"], request=request)
        return Response(
            {"detail": "If an account exists for this email, a reset link has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetConfirmView(_AuthThrottled):
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reset_password(**serializer.validated_data, request=request)
        return Response({"detail": "Password has been reset. You can now sign in."})


class PasswordChangeView(_AuthThrottled):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={200: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        services.change_password(
            user=request.user, new_password=serializer.validated_data["new_password"], request=request
        )
        return Response({"detail": "Password updated."})
