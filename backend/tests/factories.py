from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.models import Invitation, Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import OrganizationRole, WorkspaceRole

DEFAULT_PASSWORD = "Sup3r-Secret-Passw0rd!"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")
    email_verified_at = factory.LazyFunction(timezone.now)
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_PASSWORD)

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):  # type: ignore[no-untyped-def]
        if create:
            obj.save()


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Org {n}")
    slug = factory.Sequence(lambda n: f"org-{n}")


class OrganizationMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrganizationMembership

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(UserFactory)
    role = OrganizationRole.MEMBER


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Workspace {n}")
    slug = factory.Sequence(lambda n: f"workspace-{n}")


class WorkspaceMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WorkspaceMembership

    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = WorkspaceRole.AGENT


class InvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invitation

    organization = factory.SubFactory(OrganizationFactory)
    email = factory.Sequence(lambda n: f"invitee{n}@example.com")
    role = OrganizationRole.MEMBER
    token_hash = factory.Sequence(lambda n: f"{n:064d}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "workspaces.Tag"

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"tag-{n}")


class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "workspaces.Team"

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Team {n}")


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "customers.Customer"

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"customer{n}@example.org")
    identified_at = factory.LazyFunction(timezone.now)


def make_conversation(workspace, customer=None, body="Hello, I need help", **kwargs):  # type: ignore[no-untyped-def]
    """Create a conversation through the service layer (realistic denormalized state)."""
    from apps.conversations.services import Actor, start_conversation

    customer = customer or CustomerFactory(workspace=workspace)
    conversation, _ = start_conversation(
        workspace=workspace, customer=customer, actor=Actor.of_customer(customer), body=body, **kwargs
    )
    return conversation
