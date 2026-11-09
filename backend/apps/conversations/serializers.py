from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.conversations.models import (
    Attachment,
    Conversation,
    ConversationEvent,
    ConversationPriority,
    ConversationStatus,
    Message,
    MessageKind,
)
from apps.customers.serializers import TagSummarySerializer
from apps.workspaces.models import Team


class PersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)


def _user(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.get_full_name(), "email": user.email}


class TeamSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name"]
        read_only_fields = fields


class ConversationCustomerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    is_anonymous = serializers.BooleanField()


class ConversationSerializer(serializers.ModelSerializer):
    customer = ConversationCustomerSerializer(read_only=True)
    assignee = serializers.SerializerMethodField()
    team = TeamSummarySerializer(read_only=True, allow_null=True)
    tags = TagSummarySerializer(many=True, read_only=True)
    is_unread = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "number",
            "subject",
            "channel",
            "status",
            "priority",
            "customer",
            "assignee",
            "team",
            "tags",
            "last_message_at",
            "last_message_preview",
            "last_message_author_type",
            "last_customer_message_at",
            "first_response_at",
            "resolved_at",
            "is_unread",
            "ai_state",
            "ai_summary",
            "ai_summary_at",
            "human_takeover_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_assignee(self, obj: Conversation) -> dict[str, Any] | None:
        return _user(obj.assignee)

    def get_is_unread(self, obj: Conversation) -> bool:
        last_read = getattr(obj, "my_last_read_at", None)
        if obj.last_customer_message_at is None:
            return False
        return last_read is None or obj.last_customer_message_at > last_read


class ConversationCreateSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True)
    body = serializers.CharField(max_length=10000)


class ConversationUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ConversationStatus.choices, required=False)
    priority = serializers.ChoiceField(choices=ConversationPriority.choices, required=False)
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tag_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)


class AssignSerializer(serializers.Serializer):
    """Omit a field to leave it unchanged; send null to clear it."""

    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    team_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs:
            raise serializers.ValidationError("Provide assignee_id and/or team_id.")
        return attrs


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "filename", "content_type", "size"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = ["id", "kind", "author_type", "author", "body", "attachments", "created_at"]
        read_only_fields = fields

    def get_author(self, obj: Message) -> dict[str, Any] | None:
        if obj.author_user is not None:
            return _user(obj.author_user)
        if obj.author_customer is not None:
            c = obj.author_customer
            return {"id": c.id, "name": c.display_name, "email": c.email}
        return None


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=10000, required=False, allow_blank=True, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=MessageKind.choices, default=MessageKind.REPLY)


class ConversationEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = ConversationEvent
        fields = ["id", "type", "actor_type", "actor", "data", "created_at"]
        read_only_fields = fields

    def get_actor(self, obj: ConversationEvent) -> dict[str, Any] | None:
        return _user(obj.actor_user)


class ConversationCountsSerializer(serializers.Serializer):
    mine = serializers.IntegerField()
    unassigned = serializers.IntegerField()
    all = serializers.IntegerField()
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_team = serializers.DictField(child=serializers.IntegerField())


class AssigneeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
