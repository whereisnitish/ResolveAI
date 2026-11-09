"""Knowledge Hub API: /api/v1/workspaces/{ws}/knowledge/..."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.knowledge import services
from apps.knowledge.models import KnowledgeChunk, KnowledgeSource, SourceKind
from apps.tenancy.views import WorkspaceScopedViewMixin
from common.files import validate_upload
from common.rbac import Perm
from common.safe_http import UnsafeURLError, validate_url

KNOWLEDGE_FILE_TYPES = {".pdf", ".txt", ".md"}


class KnowledgeSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeSource
        fields = [
            "id",
            "kind",
            "title",
            "status",
            "error",
            "enabled",
            "filename",
            "content_type",
            "size",
            "url",
            "faq",
            "text",
            "metadata",
            "char_count",
            "chunk_count",
            "embedding_model",
            "last_indexed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class FaqItemSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500)
    answer = serializers.CharField(max_length=5000)


def _validate_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > 20:
        raise serializers.ValidationError("Metadata must be an object with at most 20 keys.")
    for k, v in value.items():
        if not isinstance(k, str) or len(k) > 50 or not isinstance(v, (str, int, float, bool)):
            raise serializers.ValidationError("Metadata keys must be short strings and values scalars.")
    return value


class KnowledgeSourceCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SourceKind.choices)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    url = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    faq = FaqItemSerializer(many=True, required=False)
    text = serializers.CharField(max_length=200_000, required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False, validators=[_validate_metadata])

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        kind = attrs["kind"]
        if kind == SourceKind.URL:
            try:
                attrs["url"] = validate_url(attrs.get("url", ""))
            except UnsafeURLError as exc:
                raise serializers.ValidationError({"url": [str(exc)]}) from exc
            attrs.setdefault("title", attrs["url"])
        elif kind == SourceKind.FAQ:
            if not attrs.get("faq"):
                raise serializers.ValidationError({"faq": ["Add at least one question and answer."]})
            if len(attrs["faq"]) > 500:
                raise serializers.ValidationError({"faq": ["At most 500 entries per source."]})
        elif kind == SourceKind.TEXT and not attrs.get("text", "").strip():
            raise serializers.ValidationError({"text": ["Text is required."]})
        if kind != SourceKind.FILE and not attrs.get("title", "").strip():
            raise serializers.ValidationError({"title": ["Title is required."]})
        return attrs


class KnowledgeSourceUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    enabled = serializers.BooleanField(required=False)
    metadata = serializers.JSONField(required=False, validators=[_validate_metadata])


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = ["id", "position", "content", "token_count", "metadata"]
        read_only_fields = fields


class SearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=1000)
    k = serializers.IntegerField(min_value=1, max_value=services.MAX_TOP_K, default=services.DEFAULT_TOP_K)
    source_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=200)
    kinds = serializers.ListField(child=serializers.ChoiceField(choices=SourceKind.choices), required=False)
    metadata = serializers.JSONField(required=False, validators=[_validate_metadata])


class SearchResultSerializer(serializers.Serializer):
    chunk_id = serializers.UUIDField()
    source_id = serializers.UUIDField()
    source_title = serializers.CharField()
    content = serializers.CharField()
    score = serializers.FloatField()
    metadata = serializers.DictField()


class KnowledgeSourceViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = KnowledgeSourceSerializer
    lookup_value_converter = "uuid"
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_by_action = {
        "list": Perm.KNOWLEDGE_VIEW,
        "retrieve": Perm.KNOWLEDGE_VIEW,
        "chunks": Perm.KNOWLEDGE_VIEW,
        "create": Perm.KNOWLEDGE_MANAGE,
        "partial_update": Perm.KNOWLEDGE_MANAGE,
        "destroy": Perm.KNOWLEDGE_MANAGE,
        "reindex": Perm.KNOWLEDGE_MANAGE,
    }

    def get_queryset(self) -> QuerySet[KnowledgeSource]:
        qs = KnowledgeSource.objects.filter(workspace=self.workspace)
        p = self.request.query_params
        if kind := p.get("kind"):
            qs = qs.filter(kind=kind)
        if status_ := p.get("status"):
            qs = qs.filter(status=status_)
        if q := p.get("q", "").strip():
            qs = qs.filter(title__icontains=q)
        return qs.order_by("-created_at")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(KnowledgeSourceSerializer(page, many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(KnowledgeSourceSerializer(self.get_object()).data)

    @extend_schema(
        request={
            "multipart/form-data": KnowledgeSourceCreateSerializer,
            "application/json": KnowledgeSourceCreateSerializer,
        },
        responses={201: KnowledgeSourceSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
        data.pop("file", None)
        serializer = KnowledgeSourceCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        attrs = serializer.validated_data
        upload = None
        if attrs["kind"] == SourceKind.FILE:
            raw = request.FILES.get("file")
            if raw is None:
                raise serializers.ValidationError({"file": ["Choose a PDF, TXT or Markdown file."]})
            upload = validate_upload(
                raw, allowed_extensions=KNOWLEDGE_FILE_TYPES, max_bytes=settings.KNOWLEDGE_MAX_FILE_BYTES, field="file"
            )
        source = services.create_source(
            workspace=self.workspace,
            kind=attrs["kind"],
            title=attrs.get("title") or (upload.filename if upload else ""),
            created_by=request.user,
            upload=upload,
            url=attrs.get("url", ""),
            faq=[dict(i) for i in attrs.get("faq", [])],
            text=attrs.get("text", ""),
            metadata=attrs.get("metadata"),
        )
        source.refresh_from_db()
        return Response(KnowledgeSourceSerializer(source).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=KnowledgeSourceUpdateSerializer, responses={200: KnowledgeSourceSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = self.get_object()
        serializer = KnowledgeSourceUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for key, value in serializer.validated_data.items():
            setattr(source, key, value)
        source.save()
        return Response(KnowledgeSourceSerializer(source).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_source(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={202: KnowledgeSourceSerializer})
    @action(detail=True, methods=["post"])
    def reindex(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = services.request_reindex(self.get_object())
        return Response(KnowledgeSourceSerializer(source).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={200: ChunkSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def chunks(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_object().chunks.order_by("position"))
        return self.get_paginated_response(ChunkSerializer(page, many=True).data)


class KnowledgeSearchView(WorkspaceScopedViewMixin, APIView):
    """Retrieval testing: see exactly what the AI would retrieve for a query."""

    permission_by_action = {"post": Perm.KNOWLEDGE_VIEW}

    @extend_schema(request=SearchRequestSerializer, responses={200: SearchResultSerializer(many=True)})
    def post(self, request: Request, workspace_id: Any) -> Response:
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        results = services.search(
            workspace=self.workspace,
            query=d["query"],
            k=d["k"],
            source_ids=d.get("source_ids"),
            kinds=d.get("kinds"),
            metadata_filter=d.get("metadata"),
        )
        return Response(SearchResultSerializer([r.__dict__ for r in results], many=True).data)
