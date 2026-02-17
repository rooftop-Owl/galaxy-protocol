#!/usr/bin/env python3
"""Unit tests for Caduceus executor implementations."""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from caduceus.executors.base import Executor
from caduceus.executors.hermes import HermesExecutor


class TestExecutor:
    """Test Executor ABC."""

    def test_cannot_instantiate(self):
        """Executor is abstract — cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract"):
            Executor()

    def test_concrete_subclass(self):
        """A concrete subclass implementing execute() can be instantiated."""
        class DummyExecutor(Executor):
            async def execute(self, order):
                return {"success": True, "response_text": "done"}

        ex = DummyExecutor()
        assert ex is not None

    @pytest.mark.asyncio
    async def test_concrete_execute(self):
        class DummyExecutor(Executor):
            async def execute(self, order):
                return {"success": True, "response_text": order["payload"]}

        ex = DummyExecutor()
        result = await ex.execute({"payload": "test"})
        assert result["success"] is True
        assert result["response_text"] == "test"


class TestHermesExecutor:
    """Test HermesExecutor filesystem bridge."""

    def test_implements_executor(self):
        assert issubclass(HermesExecutor, Executor)

    def test_creates_orders_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orders_dir = Path(tmpdir) / "galaxy-orders"
            ex = HermesExecutor({"orders_dir": str(orders_dir)})
            assert orders_dir.exists()

    @pytest.mark.asyncio
    async def test_empty_payload_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ex = HermesExecutor({
                "orders_dir": str(Path(tmpdir) / "orders"),
                "timeout": 1,
            })
            result = await ex.execute({"payload": "", "order_id": "test"})
            assert result["success"] is False
            assert "Empty payload" in result["error"]

    @pytest.mark.asyncio
    async def test_order_file_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orders_dir = Path(tmpdir) / "orders"
            ex = HermesExecutor({
                "orders_dir": str(orders_dir),
                "timeout": 2,
                "poll_interval": 0.1,
            })

            # Start execute in background (will timeout)
            async def simulate_response():
                await asyncio.sleep(0.5)
                # Check order file was written
                order_files = list(orders_dir.glob("*.json"))
                assert len(order_files) == 1
                data = json.loads(order_files[0].read_text())
                assert data["payload"] == "test order"

                # Write response file
                response_file = orders_dir.parent / f"galaxy-order-response-{order_files[0].stem}.md"
                response_file.write_text("# Response\nTest passed")

            task = asyncio.create_task(simulate_response())
            result = await ex.execute({
                "payload": "test order",
                "order_id": "test-123",
                "timestamp": time.time(),
            })
            await task

            assert result["success"] is True
            assert "Test passed" in result["response_text"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ex = HermesExecutor({
                "orders_dir": str(Path(tmpdir) / "orders"),
                "timeout": 1,
                "poll_interval": 0.1,
            })
            result = await ex.execute({
                "payload": "will timeout",
                "order_id": "timeout-test",
            })
            assert result["success"] is False
            assert "Timeout" in result["error"]

    def test_default_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ex = HermesExecutor({"orders_dir": str(Path(tmpdir) / "orders")})
            assert ex.timeout == 600
            assert ex.poll_interval == 1.0
