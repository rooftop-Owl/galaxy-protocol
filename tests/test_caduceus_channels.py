#!/usr/bin/env python3
"""Unit tests for Caduceus channel implementations."""

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

_bus_module = importlib.import_module("caduceus.bus")
MessageBus = _bus_module.MessageBus
InboundMessage = _bus_module.InboundMessage
OutboundMessage = _bus_module.OutboundMessage
BaseChannel = importlib.import_module("caduceus.channels.base").BaseChannel
WebChannel = importlib.import_module("caduceus.channels.web").WebChannel


class TestBaseChannel:
    """Test BaseChannel ABC."""

    def test_cannot_instantiate(self):
        """BaseChannel is abstract — cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract"):
            BaseChannel({}, MessageBus())

    def test_has_required_methods(self):
        import inspect

        methods = [
            m for m, _ in inspect.getmembers(BaseChannel, predicate=inspect.isfunction)
        ]
        assert "start" in methods
        assert "stop" in methods
        assert "send" in methods
        assert "_handle_message" in methods

    def test_concrete_subclass(self):
        """A concrete subclass implementing all methods can be instantiated."""

        class DummyChannel(BaseChannel):
            async def start(self):
                pass

            async def stop(self):
                pass

            async def send(self, msg):
                pass

        bus = MessageBus()
        ch = DummyChannel({}, bus)
        assert ch.bus is bus
        assert ch.config == {}

    @pytest.mark.asyncio
    async def test_handle_message_publishes_to_bus(self):
        """_handle_message creates InboundMessage and publishes to bus."""

        class DummyChannel(BaseChannel):
            async def start(self):
                pass

            async def stop(self):
                pass

            async def send(self, msg):
                pass

        bus = MessageBus()
        ch = DummyChannel({}, bus)

        await ch._handle_message(
            sender_id="user1", chat_id="chat1", content="test message"
        )

        msg = await bus.consume_inbound()
        assert msg.sender_id == "user1"
        assert msg.chat_id == "chat1"
        assert msg.content == "test message"
        assert msg.channel == "dummy"  # DummyChannel → "dummy"


class TestWebChannel:
    """Test WebChannel implementation."""

    def test_implements_base_channel(self):
        assert issubclass(WebChannel, BaseChannel)

    def test_default_config(self):
        bus = MessageBus()
        web = WebChannel({}, bus, user_store=MagicMock())
        assert web.port == 8080
        assert web.secure_cookies is False

    def test_custom_config(self):
        bus = MessageBus()
        web = WebChannel(
            {"port": 9090, "secure_cookies": True},
            bus,
            user_store=MagicMock(),
        )
        assert web.port == 9090
        assert web.secure_cookies is True

    def test_has_connections_dict(self):
        bus = MessageBus()
        web = WebChannel({}, bus, user_store=MagicMock())
        assert isinstance(web.connections, dict)
        assert len(web.connections) == 0


class TestTelegramChannel:
    """Test TelegramChannel implementation."""

    def test_importable(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        assert issubclass(TelegramChannel, BaseChannel)

    def test_format_response_compact(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        text = "# Title\n## Subtitle\n- ✅ Done\n- Item\n---\nPlain text"
        result = TelegramChannel.format_response_compact(text)

        assert "🎯 Title" in result
        assert "📌 Subtitle" in result
        assert "✅ Done" in result
        assert "---" not in result  # Separator removed

    def test_format_response_truncation(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        long_text = "A" * 2000
        result = TelegramChannel.format_response_compact(long_text)
        assert len(result) <= 1500

    def test_load_machines_new_format(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        config = {"machines": {"lab": {"host": "localhost", "repo_path": "/tmp/test"}}}
        machines = TelegramChannel._load_machines(config)
        assert "lab" in machines
        assert machines["lab"]["host"] == "localhost"

    def test_load_machines_legacy_format(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        config = {"machine_name": "legacy", "repo_path": "/tmp/test"}
        machines = TelegramChannel._load_machines(config)
        assert "legacy" in machines

    def test_is_local(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        assert TelegramChannel.is_local({"host": "localhost"}) is True
        assert TelegramChannel.is_local({"host": "127.0.0.1"}) is True
        assert TelegramChannel.is_local({"host": ""}) is True
        assert TelegramChannel.is_local({"host": "remote.server"}) is False

    def test_resolve_machine(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        bus = MessageBus()
        config = {
            "telegram_token": "test-token",
            "authorized_users": [],
            "machines": {"lab": {"host": "localhost", "repo_path": "/tmp/test"}},
            "default_machine": "lab",
        }
        ch = TelegramChannel(config, bus)

        name, machine = ch.resolve_machine(None)
        assert name == "lab"

        name, machine = ch.resolve_machine("lab")
        assert name == "lab"

        name, machine = ch.resolve_machine("nonexistent")
        assert name is None
        assert machine is None

    def test_authorization(self):
        TelegramChannel = importlib.import_module(
            "caduceus.channels.telegram"
        ).TelegramChannel

        bus = MessageBus()
        config = {
            "telegram_token": "test-token",
            "authorized_users": [123, 456],
            "machines": {"lab": {"host": "localhost", "repo_path": "/tmp/test"}},
        }
        ch = TelegramChannel(config, bus)

        assert ch.is_authorized(123) is True
        assert ch.is_authorized(456) is True
        assert ch.is_authorized(789) is False
