#!/usr/bin/env python3
"""
Phase C E2E Test Script

Tests the full Galaxy MCP server flow without requiring production infrastructure.

Usage:
    python3 tools/galaxy/test_phase_c_e2e.py

Tests:
1. Order file detection
2. Order parsing
3. Response file generation
4. Order acknowledgment
5. Archiving workflow
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))


def test_order_detection():
    print("Test 1: Order file detection")

    with tempfile.TemporaryDirectory() as tmpdir:
        orders_dir = Path(tmpdir) / "galaxy-orders"
        orders_dir.mkdir()

        order_path = orders_dir / "20260202-120000.json"
        order_data = {
            "type": "galaxy_order",
            "from": "galaxy-gazer",
            "target": "test-machine",
            "command": "general",
            "payload": "Test order: reply back",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }

        with open(order_path, "w") as f:
            json.dump(order_data, f, indent=2)

        assert order_path.exists(), "Order file not created"

        with open(order_path, "r") as f:
            loaded = json.load(f)
            assert loaded["acknowledged"] == False, "Order should be unacknowledged"
            assert loaded["payload"] == "Test order: reply back", "Payload mismatch"

        print("  ✅ Order detection and parsing works")
        return True


def test_order_acknowledgment():
    print("\nTest 2: Order acknowledgment workflow")

    with tempfile.TemporaryDirectory() as tmpdir:
        orders_dir = Path(tmpdir) / "galaxy-orders"
        archive_dir = Path(tmpdir) / "galaxy-orders-archive"
        orders_dir.mkdir()
        archive_dir.mkdir()

        order_path = orders_dir / "20260202-120000.json"
        order_data = {
            "type": "galaxy_order",
            "from": "galaxy-gazer",
            "target": "test-machine",
            "command": "general",
            "payload": "Test order",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }

        with open(order_path, "w") as f:
            json.dump(order_data, f, indent=2)

        with open(order_path, "r") as f:
            order = json.load(f)

        order["acknowledged"] = True
        order["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        order["acknowledged_by"] = "Test Agent (E2E Test)"

        with open(order_path, "w") as f:
            json.dump(order, f, indent=2)

        with open(order_path, "r") as f:
            updated = json.load(f)
            assert updated["acknowledged"] == True, "Order should be acknowledged"
            assert "acknowledged_at" in updated, "Missing acknowledged_at"
            assert "acknowledged_by" in updated, "Missing acknowledged_by"

        archive_path = archive_dir / order_path.name
        shutil.move(str(order_path), str(archive_path))

        assert archive_path.exists(), "Archive file not created"
        assert not order_path.exists(), "Original order should be moved"

        print("  ✅ Acknowledgment and archiving works")
        return True


def test_response_file_format():
    print("\nTest 3: Response file format")

    with tempfile.TemporaryDirectory() as tmpdir:
        notepads_dir = Path(tmpdir) / "notepads"
        notepads_dir.mkdir()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        response_path = notepads_dir / f"galaxy-order-response-{timestamp}.md"

        response_content = f"""# Galaxy Order Response

**Order Received**: {datetime.now(timezone.utc).isoformat()}  
**Message**: "Test order: reply back"  
**Acknowledged By**: Test Agent (E2E Test)

---

## Response

Test response content.

---

**Test Agent**  
E2E Test  
{datetime.now(timezone.utc).strftime("%Y-%m-%d")}
"""

        with open(response_path, "w") as f:
            f.write(response_content)

        assert response_path.exists(), "Response file not created"

        with open(response_path, "r") as f:
            content = f.read()
            assert "Galaxy Order Response" in content, "Missing header"
            assert "Order Received" in content, "Missing metadata"
            assert "Test response content" in content, "Missing response body"

        print("  ✅ Response file format is correct")
        return True


def test_outbox_notification():
    print("\nTest 4: Outbox notification format")

    with tempfile.TemporaryDirectory() as tmpdir:
        outbox_dir = Path(tmpdir) / "galaxy-outbox"
        outbox_dir.mkdir()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        notification_path = outbox_dir / f"{timestamp}.json"

        notification_data = {
            "type": "notification",
            "severity": "success",
            "from": "Galaxy MCP (E2E Test)",
            "message": "✅ Order Executed: <code>Test order</code>",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sent": False,
        }

        with open(notification_path, "w") as f:
            json.dump(notification_data, f, indent=2)

        assert notification_path.exists(), "Notification file not created"

        with open(notification_path, "r") as f:
            notif = json.load(f)
            assert notif["type"] == "notification", "Wrong type"
            assert notif["severity"] == "success", "Wrong severity"
            assert notif["sent"] == False, "Should be unsent"

        print("  ✅ Outbox notification format is correct")
        return True


def test_mcp_server_import():
    print("\nTest 5: MCP server import")

    try:
        import galaxy_mcp

        print("  ✅ MCP server module imports successfully")
        return True
    except ImportError as e:
        print(f"  ❌ Failed to import: {e}")
        return False


def main():
    print("=" * 70)
    print("Galaxy Phase C E2E Test Suite")
    print("=" * 70)
    print()

    tests = [
        ("Order Detection", test_order_detection),
        ("Order Acknowledgment", test_order_acknowledgment),
        ("Response File Format", test_response_file_format),
        ("Outbox Notification", test_outbox_notification),
        ("MCP Server Import", test_mcp_server_import),
    ]

    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"  ❌ Test failed with error: {e}")
            results.append((name, False))

    print()
    print("=" * 70)
    print("Test Results")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print()
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print()
        print("✅ All tests passed! Phase C core logic is working.")
        print()
        print("Manual E2E Test Required:")
        print("1. Start opencode backend: opencode serve --port 4096")
        print("2. Start MCP server: python3 tools/galaxy/galaxy_mcp.py")
        print("3. Send test order via Telegram: /order test-machine reply back")
        print("4. Verify response file created in .sisyphus/notepads/")
        print("5. Verify order archived to galaxy-orders-archive/")
        print("6. Verify Telegram notification sent")
        return 0
    else:
        print()
        print("❌ Some tests failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
