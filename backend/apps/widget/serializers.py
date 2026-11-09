"""Visitor-facing serializers. Anything here is visible to the public internet.

Never include: internal notes, agent emails, assignment/team data, tags,
customer attributes, workspace/organization ids, or AI configuration.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.conversations.models import ActorType, Conversation, Message, MessageKind
from apps.widget.models import LauncherPosition, WidgetSettings


def _author_name(message: Message) -> str:
    if message.author_type == ActorType.AGENT and message.author_user is not None:
        return message.author_user.get_short_name()
    if message.author_type == ActorType.CUSTOMER:
        return "You"
    if message.author_type == ActorType.AI:
        return "AI assistant"
    return ""


def widget_message_payload(message: Message) -> dict[str, Any]:
    assert message.kind == MessageKind.REPLY, "internal notes must never reach visitors"
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "body": message.body,
        "author_type": message.author_type,
        "author_name": _author_name(message),
        "attachments": [
            {"id": str(a.id), "filename": a.filename, "content_type": a.content_type, "size": a.size}
            for a in message.attachments.all()
        ],
        "created_at": message.created_at.isoformat(),
    }


class WidgetMessageSerializer(serializers.Serializer):
    def to_representation(self, instance: Message) -> dict[str, Any]:
        return widget_message_payload(instance)


class WidgetConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "number",
            "status",
            "last_message_preview",
            "last_message_author_type",
            "last_message_at",
            "created_at",
        ]
        read_only_fields = fields


class WidgetPublicSettingsSerializer(serializers.ModelSerializer):
    team_name = serializers.SerializerMethodField()

    class Meta:
        model = WidgetSettings
        fields = list(WidgetSettings.PUBLIC_FIELDS)
        read_only_fields = fields

    def get_team_name(self, obj: WidgetSettings) -> str:
        return obj.team_name or obj.workspace.name


class SessionRequestSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(max_length=40, help_text="The workspace's public widget id (ws_...).")
    visitor_token = serializers.CharField(max_length=100, required=False, allow_blank=True)
    page_url = serializers.CharField(max_length=500, required=False, allow_blank=True)


class SessionResponseSerializer(serializers.Serializer):
    session_token = serializers.CharField()
    expires_in = serializers.IntegerField()
    visitor_token = serializers.CharField()
    visitor = serializers.DictField()
    settings = WidgetPublicSettingsSerializer()


class VisitorMessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000, trim_whitespace=True)


class IdentifySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs:
            raise serializers.ValidationError("Provide a name or email.")
        if "email" in attrs:
            attrs["email"] = attrs["email"].strip().lower()
        if "name" in attrs:
            attrs["name"] = attrs["name"].strip()
        return attrs


class WidgetSettingsSerializer(serializers.ModelSerializer):
    """Dashboard-side (admin) representation of the widget configuration."""

    allowed_origins = serializers.ListField(child=serializers.CharField(max_length=255), required=False, max_length=50)
    brand_color = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    launcher_position = serializers.ChoiceField(choices=LauncherPosition.choices, required=False)

    class Meta:
        model = WidgetSettings
        fields = [
            "enabled",
            "allowed_origins",
            "brand_color",
            "team_name",
            "welcome_message",
            "launcher_position",
            "collect_email",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate_allowed_origins(self, value: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        cleaned: list[str] = []
        for raw in value:
            raw = raw.strip().rstrip("/")
            parts = urlsplit(raw)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query:
                raise serializers.ValidationError(
                    f"{raw!r} is not a valid origin. Use scheme://host[:port], e.g. https://www.example.com"
                )
            cleaned.append(raw.lower())
        return list(dict.fromkeys(cleaned))
