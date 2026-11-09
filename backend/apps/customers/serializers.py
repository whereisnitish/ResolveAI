from __future__ import annotations

import json
from typing import Any

from rest_framework import serializers

from apps.customers.models import Customer, CustomerNote
from apps.workspaces.models import Tag


class TagSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "color"]
        read_only_fields = fields


class UserSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()


def validate_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object.")
    if len(value) > 50:
        raise serializers.ValidationError("At most 50 attributes.")
    for key, item in value.items():
        if not isinstance(key, str) or not 0 < len(key) <= 64:
            raise serializers.ValidationError("Attribute names must be 1-64 characters.")
        if not (item is None or isinstance(item, (str, int, float, bool))):
            raise serializers.ValidationError(f"Attribute {key!r} must be a string, number, boolean or null.")
        if isinstance(item, str) and len(item) > 500:
            raise serializers.ValidationError(f"Attribute {key!r} is too long (max 500).")
    if len(json.dumps(value)) > 8000:
        raise serializers.ValidationError("Attributes are too large.")
    return value


class CustomerSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    is_anonymous = serializers.BooleanField(read_only=True)
    tags = TagSummarySerializer(many=True, read_only=True)
    conversation_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Customer
        fields = [
            "id",
            "display_name",
            "name",
            "email",
            "phone",
            "external_id",
            "attributes",
            "tags",
            "is_anonymous",
            "identified_at",
            "last_seen_at",
            "last_seen_url",
            "user_agent",
            "conversation_count",
            "created_at",
        ]
        read_only_fields = fields


class CustomerWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True)
    phone = serializers.RegexField(r"^[0-9+()\-. ]{0,32}$", required=False, allow_blank=True)
    attributes = serializers.JSONField(required=False, validators=[validate_attributes])
    tag_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class CustomerNoteSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = CustomerNote
        fields = ["id", "body", "author", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def validate_body(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Note can't be empty.")
        return value


class TimelineItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    conversation_id = serializers.UUIDField(allow_null=True)
    actor_name = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField()
