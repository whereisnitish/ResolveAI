from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.exceptions import APIException

from apps.conversations.models import Conversation
from apps.realtime.publish import send_now, visitor_group, workspace_group
from apps.tenancy.access import WorkspaceAccess, get_workspace_access
from apps.widget.auth import WidgetSession, resolve_session_token
from common.rbac import Perm

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
TYPING_MIN_INTERVAL = 1.5  # seconds between relayed typing signals per socket


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class WorkspaceConsumer(AsyncJsonWebsocketConsumer):
    """Dashboard socket: /ws/workspaces/<workspace_id>/ (session cookie auth).

    Receives ID-only events for the workspace; may send typing signals.
    """

    access: WorkspaceAccess
    group: str
    _last_typing: float = 0.0

    async def connect(self) -> None:
        user = self.scope.get("user")
        workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]
        access = await database_sync_to_async(get_workspace_access)(user, workspace_id)
        if access is None or not access.has(Perm.CONVERSATIONS_VIEW):
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.access = access
        self.group = workspace_group(access.workspace.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict) or content.get("type") != "typing":
            return
        if not self.access.has(Perm.CONVERSATIONS_REPLY) or not self._typing_allowed():
            return
        conversation = await self._conversation(content.get("conversation_id"))
        if conversation is None:
            return
        user = self.scope["user"]
        is_note = bool(content.get("note"))
        await database_sync_to_async(send_now)(
            self.group,
            {
                "type": "typing",
                "conversation_id": str(conversation.id),
                "actor": "agent",
                "user_id": str(user.id),
                "name": user.get_short_name(),
                "note": is_note,
            },
        )
        if not is_note:  # never reveal that agents are writing an internal note
            await database_sync_to_async(send_now)(
                visitor_group(conversation.customer_id),
                {
                    "type": "typing",
                    "conversation_id": str(conversation.id),
                    "actor": "agent",
                    "name": user.get_short_name(),
                },
            )

    async def broadcast(self, event: dict[str, Any]) -> None:
        await self.send_json(event["payload"])

    def _typing_allowed(self) -> bool:
        now = time.monotonic()
        if now - self._last_typing < TYPING_MIN_INTERVAL:
            return False
        self._last_typing = now
        return True

    @database_sync_to_async
    def _conversation(self, conversation_id: Any) -> Conversation | None:
        try:
            cid = uuid.UUID(str(conversation_id))
        except ValueError:
            return None
        return Conversation.objects.filter(id=cid, workspace=self.access.workspace).only("id", "customer_id").first()


class WidgetConsumer(AsyncJsonWebsocketConsumer):
    """Visitor socket: /ws/widget/.

    The session token is sent as the first frame ({"type": "auth", "token": ...})
    rather than in the URL, so it never lands in proxy/server access logs.
    Unauthenticated sockets are closed after AUTH_TIMEOUT seconds.
    Receives the visitor's own reply messages and agent typing; may send typing.
    """

    AUTH_TIMEOUT = 10
    session: WidgetSession | None = None
    group: str
    _last_typing: float = 0.0
    _auth_timer: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        await self.accept()
        self._auth_timer = asyncio.create_task(self._close_if_unauthenticated())

    async def _close_if_unauthenticated(self) -> None:
        await asyncio.sleep(self.AUTH_TIMEOUT)
        if self.session is None:
            await self.close(code=CLOSE_UNAUTHORIZED)

    async def disconnect(self, code: int) -> None:
        if self._auth_timer is not None:
            self._auth_timer.cancel()
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict):
            return
        if self.session is None:
            await self._authenticate(content)
            return
        if content.get("type") != "typing":
            return
        now = time.monotonic()
        if now - self._last_typing < TYPING_MIN_INTERVAL:
            return
        self._last_typing = now
        conversation_id = await self._own_conversation_id(content.get("conversation_id"))
        if conversation_id is None:
            return
        await database_sync_to_async(send_now)(
            workspace_group(self.session.workspace.id),
            {"type": "typing", "conversation_id": conversation_id, "actor": "customer"},
        )

    async def _authenticate(self, content: dict[str, Any]) -> None:
        if content.get("type") != "auth" or not isinstance(content.get("token"), str):
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        try:
            self.session = await database_sync_to_async(resolve_session_token)(
                content["token"], _header(self.scope, b"origin")
            )
        except APIException as exc:
            await self.close(code=CLOSE_UNAUTHORIZED if exc.status_code == 401 else CLOSE_FORBIDDEN)
            return
        if self._auth_timer is not None:
            self._auth_timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._auth_timer
        self.group = visitor_group(self.session.customer.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.send_json({"type": "ready"})

    async def broadcast(self, event: dict[str, Any]) -> None:
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _own_conversation_id(self, conversation_id: Any) -> str | None:
        assert self.session is not None
        try:
            cid = uuid.UUID(str(conversation_id))
        except ValueError:
            return None
        exists = Conversation.objects.filter(
            id=cid, workspace=self.session.workspace, customer=self.session.customer
        ).exists()
        return str(cid) if exists else None
