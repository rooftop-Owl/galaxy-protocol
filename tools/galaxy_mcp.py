#!/usr/bin/env python3
"""
Galaxy MCP Server — Agent-Powered Order Processor

Watches galaxy-orders/ directory and executes orders via opencode run --attach.
Provides tools for order polling, execution, and status tracking.

Pattern: MCPtrace lifespan background tasks
Architecture: opencode serve (persistent) + MCP server (watcher) + opencode run (executor)
"""

import asyncio
import os
import json
import subprocess
import sys
import importlib
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import List, Optional, TypedDict

from fastmcp import FastMCP

# Project root: galaxy-protocol/tools/ -> galaxy-protocol/ -> project/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
session_tracker = importlib.import_module("session_tracker")
detect_repo_root = session_tracker.detect_repo_root

opencode_runtime = importlib.import_module("opencode_runtime")
resolve_opencode_binary = opencode_runtime.resolve_opencode_binary

try:
    audit_module = importlib.import_module("audit")
    log_event = audit_module.log_event
except ImportError:

    def log_event(event_type, data, severity="info"):
        _ = (event_type, data, severity)


# Configuration
REPO_ROOT = detect_repo_root()
MODULE_ROOT = Path(__file__).parent.parent  # galaxy-protocol module root
ORDERS_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders"
ARCHIVE_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders-archive"
OUTBOX_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-outbox"
RESPONSE_DIR = REPO_ROOT / ".sisyphus/notepads"
GALAXY_CONFIG = REPO_ROOT / ".galaxy/config.json"
HEARTBEAT_FILE = REPO_ROOT / ".sisyphus/notepads/galaxy-session-heartbeat.json"

POLL_INTERVAL = 5  # seconds
OPENCODE_SERVER = os.environ.get("OPENCODE_ATTACH_URL", "http://localhost:4096")
HEARTBEAT_TIMEOUT = 120  # seconds - heartbeat older than this = session dead


class ServerState(TypedDict):
    processed_count: int
    failed_count: int
    started_at: str
    last_poll: str


# In-memory state (no compaction, persists for server lifetime)
server_state: ServerState = {
    "processed_count": 0,
    "failed_count": 0,
    "started_at": "",
    "last_poll": "",
}


def is_standby_session_active() -> bool:
    """
    Check if a /galaxy-standby session is actively running.

    Returns True if heartbeat file exists and was updated within HEARTBEAT_TIMEOUT seconds.
    """
    if not HEARTBEAT_FILE.exists():
        return False

    try:
        heartbeat = json.loads(HEARTBEAT_FILE.read_text())
        last_heartbeat = datetime.fromisoformat(heartbeat["last_heartbeat_at"])
        age_seconds = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()

        return heartbeat.get("status") == "running" and age_seconds < HEARTBEAT_TIMEOUT
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return False


async def watch_orders_loop():
    """Background task: lightweight order monitoring."""
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        server_state["last_poll"] = datetime.now(timezone.utc).isoformat()
        # Health check — actual processing happens via galaxy_execute tool calls or /galaxy-standby session


async def cleanup_old_responses():
    """Background task: cleanup response files older than 30 days."""
    while True:
        await asyncio.sleep(3600)  # Run hourly
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - (30 * 86400)
            for resp_file in RESPONSE_DIR.glob("galaxy-order-response-*.md"):
                if resp_file.stat().st_mtime < cutoff:
                    resp_file.unlink()
                    print(
                        f"[Cleanup] Removed old response: {resp_file.name}",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"[Cleanup Error] {e}", file=sys.stderr)


@asynccontextmanager
async def lifespan(server):
    """Server lifecycle: startup background tasks, cleanup on shutdown."""
    server_state["started_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[Galaxy MCP] Starting background tasks...", file=sys.stderr)

    # Launch background tasks
    watcher_task = asyncio.create_task(watch_orders_loop())
    cleanup_task = asyncio.create_task(cleanup_old_responses())

    yield

    # Shutdown cleanup
    print(f"[Galaxy MCP] Shutting down...", file=sys.stderr)
    watcher_task.cancel()
    cleanup_task.cancel()
    try:
        await asyncio.gather(watcher_task, cleanup_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass


# Initialize MCP server with lifespan
mcp = FastMCP("galaxy-standby", lifespan=lifespan)


@mcp.tool()
async def galaxy_poll() -> dict[str, object]:
    """
    Poll for unacknowledged Galaxy orders.

    Returns list of pending orders with metadata.
    """
    orders = []

    if not ORDERS_DIR.exists():
        return {"orders": [], "count": 0}

    for order_file in ORDERS_DIR.glob("*.json"):
        try:
            data = json.loads(order_file.read_text())
            if not data.get("acknowledged", False):
                orders.append(
                    {
                        "order_id": order_file.stem,
                        "payload": data["payload"],
                        "timestamp": data["timestamp"],
                        "from": data.get("from", "unknown"),
                        "target": data.get("target", "unknown"),
                        "command": data.get("command", "general"),
                    }
                )
        except Exception as e:
            print(f"[Poll Error] Failed to read {order_file}: {e}", file=sys.stderr)

    return {
        "orders": orders,
        "count": len(orders),
        "last_poll": server_state["last_poll"],
    }


@mcp.tool()
async def galaxy_execute(order_id: str) -> dict[str, object]:
    """
    Execute a Galaxy order.

    Phase D2: Delegates to /galaxy-standby persistent session if active.
    Phase D1 fallback: Spawns fresh session via opencode run --attach.

    Args:
        order_id: The order file timestamp (e.g., "20260202-062557")

    Returns:
        Execution status with response file path
    """
    order_file = ORDERS_DIR / f"{order_id}.json"
    claimed_file = ORDERS_DIR / f"{order_id}.json.processing"

    if not order_file.exists():
        log_event("order_not_found", {"order_id": order_id}, severity="warning")
        return {"error": "Order not found", "order_id": order_id}

    # Phase D2: Check if /galaxy-standby session is running
    if is_standby_session_active():
        print(
            f"[Execute] Delegating to /galaxy-standby session: {order_id}",
            file=sys.stderr,
        )
        return {
            "status": "delegated",
            "order_id": order_id,
            "executor": "galaxy-standby-session",
            "message": "Order will be processed by persistent /galaxy-standby session",
            "note": "Phase D2: Execution delegated to orchestrated session",
        }

    try:
        log_event("order_execution_started", {"order_id": order_id}, severity="info")

        # Atomic claim: rename to prevent double execution
        try:
            order_file.rename(claimed_file)
        except FileNotFoundError:
            return {
                "error": "Order already claimed by another executor",
                "order_id": order_id,
            }

        # Read order from claimed file
        order = json.loads(claimed_file.read_text())
        payload = order["payload"]

        MAX_PAYLOAD_LEN = 10000
        if len(payload) > MAX_PAYLOAD_LEN:
            claimed_file.rename(order_file)
            return {
                "error": f"Payload too long ({len(payload)} > {MAX_PAYLOAD_LEN})",
                "order_id": order_id,
            }
        if not payload.strip():
            claimed_file.rename(order_file)
            return {"error": "Empty payload", "order_id": order_id}

        opencode_binary, resolution_error = resolve_opencode_binary()
        if not opencode_binary:
            claimed_file.rename(order_file)
            log_event(
                "order_execution_unavailable",
                {
                    "order_id": order_id,
                    "reason": resolution_error,
                },
                severity="error",
            )
            return {
                "error": f"OpenCode runtime unavailable: {resolution_error}",
                "order_id": order_id,
                "status": "unavailable",
            }

        print(f"[Execute] Order {order_id}: {payload[:50]}...", file=sys.stderr)

        # Execute via opencode run --attach (full agent reasoning)
        result = subprocess.run(
            [
                opencode_binary,
                "run",
                "--attach",
                OPENCODE_SERVER,
                "--format",
                "json",
                payload,
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
            cwd=str(REPO_ROOT),
        )

        execution_success = result.returncode == 0

        # Parse JSON output if available
        try:
            output_data = json.loads(result.stdout) if result.stdout else {}
            response_text = output_data.get("content", result.stdout)
        except json.JSONDecodeError:
            response_text = result.stdout

        # Write response file
        response_file = RESPONSE_DIR / f"galaxy-order-response-{order_id}.md"
        response_content = f"""# Galaxy Order Response

**Order Received**: {order["timestamp"]}  
**Message**: "{payload}"  
**Acknowledged By**: Galaxy MCP Server

---

## Response

{response_text}

{f"**Errors**:\n{result.stderr}" if result.stderr else ""}

---

**Galaxy MCP Server**  
{datetime.now(timezone.utc).isoformat()}
"""
        response_file.write_text(response_content)

        # Update order JSON — set acknowledged
        order["acknowledged"] = True
        order["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        order["acknowledged_by"] = "Galaxy MCP Server"

        # Archive order
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_file = ARCHIVE_DIR / f"{order_id}.json"
        archive_file.write_text(json.dumps(order, indent=2))
        claimed_file.unlink()

        # Write outbox notification
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        severity = "success" if execution_success else "warning"
        message = (
            f"✅ <b>Order Executed</b>\n\n<code>{payload[:80]}</code>\n\nResponse written to notepads."
            if execution_success
            else f"⚠️ <b>Order Failed</b>\n\n<code>{payload[:80]}</code>\n\nCheck response file for details."
        )

        outbox_file = OUTBOX_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        outbox_file.write_text(
            json.dumps(
                {
                    "type": "notification",
                    "severity": severity,
                    "from": "Galaxy MCP Server",
                    "message": message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sent": False,
                },
                indent=2,
            )
        )

        # Update stats and audit log
        if execution_success:
            server_state["processed_count"] += 1
            log_event(
                "order_executed_success",
                {
                    "order_id": order_id,
                    "payload_preview": payload[:100],
                    "exit_code": result.returncode,
                },
                severity="info",
            )
        else:
            server_state["failed_count"] += 1
            log_event(
                "order_executed_failure",
                {
                    "order_id": order_id,
                    "payload_preview": payload[:100],
                    "exit_code": result.returncode,
                },
                severity="error",
            )

        print(
            f"[Execute] {'Success' if execution_success else 'Failed'}: {order_id}",
            file=sys.stderr,
        )

        return {
            "status": "success" if execution_success else "failed",
            "order_id": order_id,
            "response_file": str(response_file),
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        server_state["failed_count"] += 1
        try:
            claimed_file.rename(order_file)
        except OSError:
            pass
        return {
            "error": "Execution timeout (5 min)",
            "order_id": order_id,
            "status": "timeout",
        }
    except Exception as e:
        server_state["failed_count"] += 1
        try:
            claimed_file.rename(order_file)
        except OSError:
            pass
        print(f"[Execute Error] {e}", file=sys.stderr)
        return {"error": str(e), "order_id": order_id, "status": "error"}


@mcp.tool()
async def galaxy_acknowledge(order_id: str, skip_execution: bool = False) -> dict[str, object]:
    """
    Acknowledge an order without executing (for manual handling).

    Args:
        order_id: The order file timestamp
        skip_execution: If True, archives without execution

    Returns:
        Acknowledgment status
    """
    order_file = ORDERS_DIR / f"{order_id}.json"

    if not order_file.exists():
        return {"error": "Order not found", "order_id": order_id}

    try:
        order = json.loads(order_file.read_text())
        order["acknowledged"] = True
        order["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        order["acknowledged_by"] = "Galaxy MCP Server (manual)"

        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_file = ARCHIVE_DIR / f"{order_id}.json"
        archive_file.write_text(json.dumps(order, indent=2))
        order_file.unlink()

        return {"status": "acknowledged", "order_id": order_id}

    except Exception as e:
        return {"error": str(e), "order_id": order_id}


@mcp.tool()
async def galaxy_status() -> dict[str, object]:
    """
    Get Galaxy MCP server status and statistics.

    Returns server uptime, order counts, and health indicators.
    """
    started = datetime.fromisoformat(server_state["started_at"])
    uptime_seconds = (datetime.now(timezone.utc) - started).total_seconds()

    # Check if opencode serve is reachable
    opencode_healthy = False
    try:
        health_check = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                f"{OPENCODE_SERVER}/health",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        opencode_healthy = health_check.stdout == "200"
    except (subprocess.SubprocessError, OSError, subprocess.TimeoutExpired):
        pass

    # Count pending orders
    pending = 0
    if ORDERS_DIR.exists():
        for order_file in ORDERS_DIR.glob("*.json"):
            try:
                data = json.loads(order_file.read_text())
                if not data.get("acknowledged", False):
                    pending += 1
            except (json.JSONDecodeError, OSError, KeyError):
                pass

    # Get machine identity
    machine_name = "unknown"
    try:
        if GALAXY_CONFIG.exists():
            config = json.loads(GALAXY_CONFIG.read_text())
            machine_name = config.get("default_machine", "unknown")
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    # Check standby session status
    standby_active = is_standby_session_active()
    standby_info = {}
    if standby_active and HEARTBEAT_FILE.exists():
        try:
            heartbeat = json.loads(HEARTBEAT_FILE.read_text())
            standby_info = {
                "session_active": True,
                "orders_processed": heartbeat.get("orders_processed", 0),
                "success_count": heartbeat.get("success_count", 0),
                "failure_count": heartbeat.get("failure_count", 0),
                "context_utilization_pct": heartbeat.get("context_utilization_pct", 0),
                "last_heartbeat": heartbeat.get("last_heartbeat_at", "unknown"),
                "session_id": heartbeat.get("session_id", "unknown"),
            }
        except (json.JSONDecodeError, KeyError, OSError):
            standby_info = {
                "session_active": True,
                "error": "Could not read heartbeat details",
            }
    else:
        standby_info = {"session_active": False}

    return {
        "machine": machine_name,
        "uptime_seconds": uptime_seconds,
        "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
        "processed": server_state["processed_count"],
        "failed": server_state["failed_count"],
        "pending": pending,
        "last_poll": server_state["last_poll"],
        "opencode_server": OPENCODE_SERVER,
        "opencode_healthy": opencode_healthy,
        "started_at": server_state["started_at"],
        "standby_session": standby_info,
        "execution_mode": "Phase D2: Orchestrated Session" if standby_active else "Phase D1: Fresh Sessions",
    }


if __name__ == "__main__":
    print("[Galaxy MCP] Server starting...", file=sys.stderr)
    print(f"[Galaxy MCP] Watching: {ORDERS_DIR}", file=sys.stderr)
    print(f"[Galaxy MCP] OpenCode server: {OPENCODE_SERVER}", file=sys.stderr)
    mcp.run(transport="stdio")
