from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.accounts.models import User, UserManager
from apps.audit import services as audit
from apps.audit.services import AuditAction
from apps.organizations.models import Organization
from apps.organizations.services import accept_invitation, create_organization
from apps.workspaces.models import Workspace
from common.email import queue_email
from common.exceptions import ConflictError, ServiceError

EMAIL_VERIFICATION_SALT = "accounts.email-verification"


@dataclass(frozen=True)
class RegistrationResult:
    user: User
    organization: Organization | None
    workspace: Workspace | None


@transaction.atomic
def register_user(
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str | None,
    country: str = "",
    invitation_token: str | None = None,
    request: HttpRequest | None = None,
) -> RegistrationResult:
    """Create a user and either a new organization or join via invitation.

    Without an invitation the user becomes Owner of a new organization with a
    default workspace. Everything happens in one transaction.
    """
    email = UserManager.normalize_email_address(email)
    if User.objects.filter(email=email).exists():
        raise ConflictError("An account with this email already exists.", code="email_taken")

    user = User.objects.create_user(email=email, password=password, full_name=full_name.strip())
    audit.record(AuditAction.USER_REGISTERED, actor=user, request=request, target=user)

    org: Organization | None = None
    workspace: Workspace | None = None
    if invitation_token:
        membership = accept_invitation(raw_token=invitation_token, user=user, request=request)
        org = membership.organization
    else:
        if not organization_name:
            raise ServiceError("Organization name is required.", code="organization_required")
        org, workspace = create_organization(name=organization_name, owner=user, country=country, request=request)

    if not user.is_email_verified:
        send_verification_email(user)
    return RegistrationResult(user=user, organization=org, workspace=workspace)


# -----------------------------------------------------------------------------
# Email verification (stateless signed token, bound to the current email)
# -----------------------------------------------------------------------------
def make_email_verification_token(user: User) -> str:
    return signing.dumps({"uid": str(user.id), "email": user.email}, salt=EMAIL_VERIFICATION_SALT)


def send_verification_email(user: User) -> None:
    token = make_email_verification_token(user)
    queue_email(
        to=user.email,
        subject="Verify your email for ResolveAI",
        body=(
            f"Hi {user.get_short_name()},\n\n"
            f"Confirm your email address: {settings.FRONTEND_URL}/verify-email?token={token}\n\n"
            "If you didn't create a ResolveAI account, you can ignore this email."
        ),
    )


def verify_email(token: str, request: HttpRequest | None = None) -> User:
    try:
        payload = signing.loads(
            token, salt=EMAIL_VERIFICATION_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS
        )
    except signing.SignatureExpired as exc:
        raise ServiceError("This verification link has expired.", code="token_expired") from exc
    except signing.BadSignature as exc:
        raise ServiceError("This verification link is invalid.", code="token_invalid") from exc

    user = User.objects.filter(id=payload.get("uid"), email=payload.get("email"), is_active=True).first()
    if user is None:
        raise ServiceError("This verification link is invalid.", code="token_invalid")
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at", "updated_at"])
        audit.record(AuditAction.USER_EMAIL_VERIFIED, actor=user, request=request, target=user)
    return user


# -----------------------------------------------------------------------------
# Password reset (Django token generator: single-use, invalidated by password change/login)
# -----------------------------------------------------------------------------
def request_password_reset(email: str, request: HttpRequest | None = None) -> None:
    """Always succeeds from the caller's perspective to prevent account enumeration."""
    user = User.objects.filter(email=UserManager.normalize_email_address(email), is_active=True).first()
    if user is None:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    queue_email(
        to=user.email,
        subject="Reset your ResolveAI password",
        body=(
            f"Hi {user.get_short_name()},\n\n"
            f"Reset your password: {settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}\n\n"
            "This link expires in 1 hour. If you didn't request a reset, ignore this email."
        ),
    )
    audit.record(AuditAction.USER_PASSWORD_RESET_REQUESTED, actor=user, request=request, target=user)


def _user_from_uid(uid: str) -> User | None:
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        return User.objects.filter(pk=uuid.UUID(pk), is_active=True).first()
    except (TypeError, ValueError, OverflowError, UnicodeDecodeError):
        return None


def reset_password(*, uid: str, token: str, new_password: str, request: HttpRequest | None = None) -> User:
    user = _user_from_uid(uid)
    if user is None or not default_token_generator.check_token(user, token):
        raise ServiceError("This password reset link is invalid or has expired.", code="token_invalid")
    user.set_password(new_password)
    # Existing sessions die automatically: Django stores a hash derived from the
    # password in each session and rejects it once the password changes.
    user.save(update_fields=["password", "updated_at"])
    audit.record(AuditAction.USER_PASSWORD_RESET, actor=user, request=request, target=user)
    return user


def change_password(*, user: User, new_password: str, request: HttpRequest) -> None:
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    # Keep the current session; every other session is invalidated by the hash change.
    update_session_auth_hash(request, user)
    audit.record(AuditAction.USER_PASSWORD_CHANGED, actor=user, request=request, target=user)
