"""Regression test for the production channel layer configuration against real Redis.

Unit tests use the in-memory layer, which hid a real bug: with redis-py >= 8
(default socket_timeout = 5s) channels_redis's 5s blocking receive raced the
socket timeout and crashed every WebSocket consumer after ~5 idle seconds.

Skipped automatically when the dev Redis isn't reachable (e.g. minimal CI).
"""

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urlparse

import pytest
from channels_redis.core import RedisChannelLayer

from config.settings import base

HOST_CONFIG = base.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]


def _redis_reachable() -> bool:
    url = urlparse(HOST_CONFIG["address"])
    try:
        with socket.create_connection((url.hostname, url.port or 6379), timeout=1):
            return True
    except OSError:
        return False


def test_socket_timeout_exceeds_blocking_receive_window():
    assert HOST_CONFIG["socket_timeout"] > RedisChannelLayer.brpop_timeout * 2


@pytest.mark.asyncio
@pytest.mark.skipif(not _redis_reachable(), reason="dev Redis not reachable")
async def test_idle_receive_survives_longer_than_brpop_window():
    layer = RedisChannelLayer(**base.CHANNEL_LAYERS["default"]["CONFIG"])
    channel = await layer.new_channel()
    try:
        # Nothing is sent: the receive must simply keep waiting (our own timeout fires),
        # not blow up with redis.exceptions.TimeoutError.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(layer.receive(channel), timeout=RedisChannelLayer.brpop_timeout + 2)
        await layer.send(channel, {"type": "ping"})
        assert (await asyncio.wait_for(layer.receive(channel), timeout=5))["type"] == "ping"
    finally:
        await layer.flush()
