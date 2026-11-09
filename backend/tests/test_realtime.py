"""WebSocket consumers: auth, origin checks, tenant isolation and event delivery."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore

from apps.conversations.services import Actor, post_message
from apps.customers.services import get_or_create_visitor
from apps.widget.auth import issue_session_token
from apps.widget.models import WidgetSettings
from config.asgi import application
from tests.conftest import make_tenant
from tests.factories import make_conversation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

DASHBOARD_ORIGIN = b"http://localhost:3000"


@sync_to_async
def _session_cookie(user: Any) -> bytes:
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.create()
    return f"resolveai_session={store.session_key}".encode()


async def dashboard_socket(
    workspace_id: Any, user: Any = None, origin: bytes = DASHBOARD_ORIGIN
) -> WebsocketCommunicator:
    headers = [(b"origin", origin)]
    if user is not None:
        headers.append((b"cookie", await _session_cookie(user)))
    return WebsocketCommunicator(application, f"/ws/workspaces/{workspace_id}/", headers=headers)


async def widget_socket(origin: bytes = b"https://shop.example.com") -> WebsocketCommunicator:
    return WebsocketCommunicator(application, "/ws/widget/", headers=[(b"origin", origin)])


@sync_to_async
def _tenants() -> tuple[Any, Any]:
    return make_tenant("Acme"), make_tenant("Globex")


@sync_to_async
def _visitor_token(workspace: Any) -> tuple[str, Any]:
    customer, identity, _ = get_or_create_visitor(workspace=workspace, raw_token=None)
    return issue_session_token(identity), customer


async def _drain(comm: WebsocketCommunicator, timeout: float = 0.3) -> list[dict[str, Any]]:
    # receive_nothing() waits without cancelling the app (a timed-out receive_* would kill it).
    events = []
    while not await comm.receive_nothing(timeout=timeout):
        events.append(await comm.receive_json_from(timeout=1))
    return events


class TestDashboardSocket:
    async def test_member_receives_id_only_events(self):
        a, _ = await _tenants()
        comm = await dashboard_socket(a.workspace.id, a.ws_agent)
        connected, _ = await comm.connect()
        assert connected
        conv = await sync_to_async(make_conversation)(a.workspace, body="secret body text")
        events = await _drain(comm)
        types = {e["type"] for e in events}
        assert {"conversation.created", "message.created"} <= types
        assert all(e.get("conversation_id") == str(conv.id) for e in events)
        assert "secret body text" not in str(events)  # dashboard events carry ids only
        await comm.disconnect()

    async def test_rejections(self):
        a, b = await _tenants()
        cases = [
            await dashboard_socket(a.workspace.id),  # anonymous
            await dashboard_socket(b.workspace.id, a.owner),  # other tenant
            await dashboard_socket(a.workspace.id, a.billing_admin),  # no workspace access
            await dashboard_socket(a.workspace.id, a.owner, origin=b"https://evil.example"),  # CSWSH
        ]
        for comm in cases:
            connected, _ = await comm.connect()
            assert not connected

    async def test_other_workspace_events_not_received(self):
        a, b = await _tenants()
        comm = await dashboard_socket(a.workspace.id, a.owner)
        assert (await comm.connect())[0]
        await sync_to_async(make_conversation)(b.workspace)
        assert await _drain(comm) == []
        await comm.disconnect()


class TestWidgetSocket:
    async def test_requires_auth_frame(self):
        _a, _ = await _tenants()
        comm = await widget_socket()
        assert (await comm.connect())[0]
        await comm.send_json_to({"type": "typing", "conversation_id": "x"})
        output = await comm.receive_output(timeout=1)
        assert output["type"] == "websocket.close" and output["code"] == 4401

    async def test_bad_token_and_disallowed_origin(self):
        a, _ = await _tenants()
        token, _ = await _visitor_token(a.workspace)
        comm = await widget_socket()
        await comm.connect()
        await comm.send_json_to({"type": "auth", "token": token + "tampered"})
        assert (await comm.receive_output(timeout=1))["code"] == 4401

        await sync_to_async(WidgetSettings.objects.update_or_create)(
            workspace=a.workspace, defaults={"allowed_origins": ["https://shop.example.com"]}
        )
        comm = await widget_socket(origin=b"https://evil.example")
        await comm.connect()
        await comm.send_json_to({"type": "auth", "token": token})
        assert (await comm.receive_output(timeout=1))["code"] == 4403

    async def test_visitor_receives_replies_but_never_notes(self):
        a, _ = await _tenants()
        token, customer = await _visitor_token(a.workspace)
        conv = await sync_to_async(make_conversation)(a.workspace, customer)
        comm = await widget_socket()
        await comm.connect()
        await comm.send_json_to({"type": "auth", "token": token})
        assert (await comm.receive_json_from(timeout=1)) == {"type": "ready"}

        await sync_to_async(post_message)(
            conversation=conv, actor=Actor.agent(a.ws_agent), body="Internal only", kind="note"
        )
        await sync_to_async(post_message)(conversation=conv, actor=Actor.agent(a.ws_agent), body="Hi! How can I help?")
        events = await _drain(comm)
        assert [e["message"]["body"] for e in events if e["type"] == "message.created"] == ["Hi! How can I help?"]
        assert "Internal only" not in str(events)
        await comm.disconnect()

    async def test_visitor_does_not_receive_other_visitors_messages(self):
        a, _ = await _tenants()
        token, _ = await _visitor_token(a.workspace)
        other_conv = await sync_to_async(make_conversation)(a.workspace)
        comm = await widget_socket()
        await comm.connect()
        await comm.send_json_to({"type": "auth", "token": token})
        await comm.receive_json_from(timeout=1)
        await sync_to_async(post_message)(conversation=other_conv, actor=Actor.agent(a.ws_agent), body="not yours")
        assert await _drain(comm) == []
        await comm.disconnect()


class TestTyping:
    async def test_typing_relayed_both_ways_and_notes_hidden(self):
        a, _ = await _tenants()
        token, customer = await _visitor_token(a.workspace)
        conv = await sync_to_async(make_conversation)(a.workspace, customer)
        agent = await dashboard_socket(a.workspace.id, a.ws_agent)
        await agent.connect()
        visitor = await widget_socket()
        await visitor.connect()
        await visitor.send_json_to({"type": "auth", "token": token})
        await visitor.receive_json_from(timeout=1)
        await _drain(agent)

        await visitor.send_json_to({"type": "typing", "conversation_id": str(conv.id)})
        assert (await agent.receive_json_from(timeout=1))["actor"] == "customer"

        await agent.send_json_to({"type": "typing", "conversation_id": str(conv.id), "note": True})
        assert await _drain(visitor) == []  # writing a note is invisible to the customer
        await asyncio.sleep(1.6)  # per-socket typing throttle
        await agent.send_json_to({"type": "typing", "conversation_id": str(conv.id)})
        event = await visitor.receive_json_from(timeout=1)
        assert event["type"] == "typing" and event["actor"] == "agent" and "user_id" not in event
        await agent.disconnect()
        await visitor.disconnect()

    async def test_viewer_typing_ignored_and_foreign_conversation_ignored(self):
        a, b = await _tenants()
        conv_b = await sync_to_async(make_conversation)(b.workspace)
        viewer = await dashboard_socket(a.workspace.id, a.ws_viewer)
        await viewer.connect()
        owner_b = await dashboard_socket(b.workspace.id, b.owner)
        await owner_b.connect()
        await _drain(owner_b)
        await viewer.send_json_to({"type": "typing", "conversation_id": str(conv_b.id)})
        assert await _drain(owner_b) == []
        await viewer.disconnect()
        await owner_b.disconnect()
