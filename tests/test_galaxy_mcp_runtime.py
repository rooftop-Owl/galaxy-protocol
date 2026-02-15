#!/usr/bin/env python3

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

galaxy_mcp = pytest.importorskip("galaxy_mcp")


@pytest.mark.asyncio
@patch("galaxy_mcp.resolve_opencode_binary", return_value=(None, "binary missing"))
async def test_galaxy_execute_unavailable_requeues_order(_mock_resolve, tmp_path, monkeypatch):
    orders_dir = tmp_path / ".sisyphus" / "notepads" / "galaxy-orders"
    archive_dir = tmp_path / ".sisyphus" / "notepads" / "galaxy-orders-archive"
    outbox_dir = tmp_path / ".sisyphus" / "notepads" / "galaxy-outbox"
    response_dir = tmp_path / ".sisyphus" / "notepads"

    orders_dir.mkdir(parents=True, exist_ok=True)
    order_id = "20260215-010101"
    order_path = orders_dir / f"{order_id}.json"
    order_path.write_text(
        json.dumps(
            {
                "payload": "Run diagnostics",
                "timestamp": "2026-02-15T01:01:01Z",
                "acknowledged": False,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(galaxy_mcp, "ORDERS_DIR", orders_dir)
    monkeypatch.setattr(galaxy_mcp, "ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(galaxy_mcp, "OUTBOX_DIR", outbox_dir)
    monkeypatch.setattr(galaxy_mcp, "RESPONSE_DIR", response_dir)

    result = await galaxy_mcp.galaxy_execute.fn(order_id)

    assert result["status"] == "unavailable"
    assert "binary missing" in result["error"]
    assert order_path.exists()
    assert not (orders_dir / f"{order_id}.json.processing").exists()
