from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.tenancy.views import WorkspaceScopedViewMixin
from apps.workflows.engine import ACTIONS, FIELDS, OPERATORS, validate_definition
from apps.workflows.models import Trigger, Workflow, WorkflowExecution
from common.rbac import Perm


class WorkflowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "trigger",
            "trigger_config",
            "conditions",
            "actions",
            "position",
            "run_count",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "run_count", "last_run_at", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        inst = self.instance
        validate_definition(
            self.context["workspace"],
            attrs.get("trigger", inst.trigger if inst else ""),
            attrs.get("trigger_config", inst.trigger_config if inst else {}) or {},
            attrs.get("conditions", inst.conditions if inst else {}) or {},
            attrs.get("actions", inst.actions if inst else []),
        )
        return attrs


class WorkflowExecutionSerializer(serializers.ModelSerializer):
    conversation_number = serializers.IntegerField(source="conversation.number", default=None, read_only=True)

    class Meta:
        model = WorkflowExecution
        fields = ["id", "conversation", "conversation_number", "trigger", "status", "results", "error", "created_at"]
        read_only_fields = fields


class WorkflowViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = WorkflowSerializer
    lookup_value_converter = "uuid"
    pagination_class = None
    permission_by_action = {
        "list": Perm.WORKFLOWS_VIEW,
        "retrieve": Perm.WORKFLOWS_VIEW,
        "executions": Perm.WORKFLOWS_VIEW,
        "builder": Perm.WORKFLOWS_VIEW,
        "create": Perm.WORKFLOWS_MANAGE,
        "partial_update": Perm.WORKFLOWS_MANAGE,
        "destroy": Perm.WORKFLOWS_MANAGE,
    }

    def get_queryset(self) -> QuerySet[Workflow]:
        return Workflow.objects.filter(workspace=self.workspace)

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "workspace": self.workspace}

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(WorkflowSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(WorkflowSerializer(self.get_object()).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        wf = s.save(workspace=self.workspace, created_by=request.user)
        return Response(WorkflowSerializer(wf).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s = self.get_serializer(self.get_object(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(WorkflowSerializer(s.save()).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: WorkflowExecutionSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def executions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = self.get_object().executions.select_related("conversation")[:100]
        return Response(WorkflowExecutionSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="schema")
    def builder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Builder metadata so the UI never hard-codes what the engine supports."""
        return Response(
            {
                "triggers": [{"id": t.value, "label": t.label} for t in Trigger],
                "fields": [{"id": k, "label": v} for k, v in FIELDS.items()],
                "operators": sorted(OPERATORS),
                "actions": [{"id": k, "params": v} for k, v in ACTIONS.items()],
            }
        )
