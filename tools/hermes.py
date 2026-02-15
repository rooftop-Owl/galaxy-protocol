#!/usr/bin/env python3
"""
Hermes - The Galaxy Messenger

Lightweight daemon that polls for Galaxy orders and delivers them to the agent.
His reason for living is to deliver, not to talk.

Costs nothing when idle. No LLM needed for polling.
Runs forever on minimal resources (~5MB RAM).

Usage:
    python3 tools/galaxy/hermes.py [--interval 30] [--server http://localhost:4096]
"""

import argparse
import importlib
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Galaxy response logger
try:
    response_logger = importlib.import_module("response_logger")
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    response_logger = importlib.import_module("response_logger")

log_response = response_logger.log_response

opencode_runtime = importlib.import_module("opencode_runtime")
resolve_opencode_binary = opencode_runtime.resolve_opencode_binary

session_tracker = importlib.import_module("session_tracker")
detect_repo_root = session_tracker.detect_repo_root
log_event = session_tracker.log_event
session_file_path = session_tracker.session_file_path

# Paths
# PHASE 2: Production mode - orders/responses in parent repo, not submodule
REPO_ROOT = detect_repo_root()
MODULE_ROOT = Path(__file__).parent.parent
ORDERS_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders"
ARCHIVE_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders-archive"
RESPONSE_DIR = REPO_ROOT / ".sisyphus/notepads"
OUTBOX_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-outbox"
HEARTBEAT_FILE = REPO_ROOT / ".sisyphus/notepads/galaxy-session-heartbeat.json"
GALAXY_CONFIG = REPO_ROOT / ".galaxy/config.json"  # Config stays in parent
SESSION_FILE = session_file_path(REPO_ROOT)
CORRUPTED_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders-corrupted"

# State
running = True
stats = {
    "started_at": "",
    "orders_processed": 0,
    "failure_count": 0,
    "last_poll_at": "",
}


# --- Signal Handling ---


def shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# --- Order Processing ---


def build_prompt(payload):
    """Wrap payload with context hints and command-specific routing."""
    # Detect /stars commands and route to star-curator protocol
    if payload.strip().startswith("/stars"):
        return (
            "[Galaxy Order: /stars command]\n"
            "\n"
            "You are the STAR CURATOR. Execute the /stars command using the star-curator protocol.\n"
            "\n"
            "DATA FILE: .sisyphus/stars.json (this is the source of truth)\n"
            "SYNC SCRIPT: tools/galaxy/stars-sync.sh\n"
            "\n"
            "For /stars list:\n"
            "1. Read .sisyphus/stars.json with the Read tool\n"
            "2. Parse the JSON to extract lists and repos\n"
            "3. Return a summary: list names with repo counts\n"
            "\n"
            "For /stars audit:\n"
            "1. Fetch GitHub stars: gh api user/starred --paginate --jq '.[].full_name'\n"
            "2. Compare against .sisyphus/stars.json repos\n"
            "3. Report orphans (starred but not in config)\n"
            "\n"
            "RESPOND CONCISELY for Telegram.\n"
            "\n"
            "Command: " + payload
        )

    # Default prompt for general orders
    return (
        "[Galaxy Order via Telegram]\n"
        "\n"
        "MODE: This is a Telegram CONVERSATION. Chat, discuss, answer questions.\n"
        "Do NOT build, code, or create files here. Substantial work happens in the\n"
        "building environment (opencode sessions), not through Telegram.\n"
        "If the user asks you to build something, acknowledge and note it — the\n"
        "building environment will pick it up.\n"
        "\n"
        "WORKSPACE: You may create files in the project as directed.\n"
        "- You may READ files anywhere for context\n"
        "- Follow the user's instructions about where to write files.\n"
        "\n"
        "Conversation history: .sisyphus/notepads/galaxy-orders-archive/ (orders) "
        "and .sisyphus/notepads/galaxy-order-response-*.md (responses)\n"
        "Read ONLY the last 3 responses if you need context. Do NOT read all history.\n"
        "\n"
        "RESPOND CONCISELY. This is a Telegram chat — keep replies short and direct.\n"
        "\n" + payload
    )


def process_order(order_file, server_url):
    """Process a single order file. Every order goes to the agent."""
    order_id = order_file.stem
    claimed_file = order_file.with_suffix(".json.processing")
    start_time = time.time()

    try:
        try:
            order_file.rename(claimed_file)
        except FileNotFoundError:
            return False

        order = json.loads(claimed_file.read_text())
        # Use order_id from JSON if present (for Telegram orders with custom IDs)
        order_id = order.get("order_id", order_id)
        payload = order.get("payload", "").strip()
        priority = order.get("priority", "normal")
        project = order.get("project", "main")
        media = order.get("media", None)
        order["priority"] = priority
        order["project"] = project
        order["media"] = media

        if not payload and not media:
            claimed_file.rename(order_file)
            return False

        print(f"  >> {payload[:80]}")

        prompt = build_prompt(payload)
        response_text = call_agent(prompt, server_url)

        latency_ms = int((time.time() - start_time) * 1000)

        # Write response file (for backward compat with existing readers)
        response_file = write_response(order_id, order, payload, response_text)

        # Archive order
        archive_order(order_id, order, claimed_file)

        # Send notification
        send_notification(order_id, payload, response_text, order.get("chat_id"))

        # Log to structured telemetry
        log_response(
            order_id=order_id,
            status="delivered",
            response_text=response_text,
            channel=order.get("channel", "telegram"),
            latency_ms=latency_ms,
            payload=payload,
        )

        # Delete response file now that it's logged
        try:
            response_file.unlink()
        except OSError:
            pass  # File already consumed by notification sender, ignore

        stats["orders_processed"] = int(stats.get("orders_processed", 0)) + 1
        return True

    except Exception as e:
        print(f"  ERR {order_id}: {e}")
        stats["failure_count"] = int(stats.get("failure_count", 0)) + 1

        # Log failure (extract order/payload safely)
        latency_ms = int((time.time() - start_time) * 1000)
        try:
            order_data = json.loads(claimed_file.read_text()) if claimed_file.exists() else {}
            log_response(
                order_id=order_id,
                status="failed",
                error=str(e),
                channel=order_data.get("channel", "telegram"),
                latency_ms=latency_ms,
                payload=order_data.get("payload"),
            )
        except Exception:
            # Logging failed too, just skip it
            pass

        try:
            if claimed_file.exists():
                claimed_file.rename(order_file)
        except OSError:
            pass
        return False


def _load_session_id():
    """Load persistent session ID."""
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text())
            return data.get("session_id")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_session_id(session_id):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


def call_agent(payload, server_url):
    _ = server_url
    session_id = _load_session_id()
    opencode_binary, resolution_error = resolve_opencode_binary()
    if not opencode_binary:
        return f"Agent execution unavailable: {resolution_error}"

    def _run_opencode(prompt, sid=None):
        cmd = [opencode_binary, "run", "--format", "json"]
        if sid:
            cmd.extend(["--session", sid])
        cmd.append(prompt)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(REPO_ROOT),
        )

    try:
        result = _run_opencode(payload, session_id)

        if session_id and result.returncode != 0:
            stderr = (result.stderr or "").lower()
            if "session" in stderr and ("not found" in stderr or "invalid" in stderr or "expired" in stderr):
                log_event(
                    "backend_session_invalid",
                    component="hermes",
                    session_id=session_id,
                    action="recreate",
                )
                result = _run_opencode(payload)

        # Extract session ID from JSON output (first line has it)
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    sid = data.get("sessionID")
                    if sid:
                        _save_session_id(sid)
                        if sid != session_id:
                            log_event(
                                "backend_session_assigned",
                                component="hermes",
                                session_id=sid,
                                previous_session_id=session_id,
                                reason="agent_response",
                            )
                        break
                except json.JSONDecodeError:
                    continue

        if result.returncode == 0 and result.stdout:
            return extract_agent_response(result.stdout)
        else:
            error = result.stderr[:500] if result.stderr else "Unknown error"
            return "Agent execution failed (exit %d)\n\n%s" % (result.returncode, error)
    except subprocess.TimeoutExpired:
        return "Agent execution timed out (3 min limit)"
    except Exception as e:
        return "Agent connection error: %s" % e


def bootstrap_session(server_url):
    _ = server_url
    existing_session_id = _load_session_id()
    if existing_session_id:
        log_event(
            "backend_session_reused",
            component="hermes",
            session_id=existing_session_id,
        )
        return existing_session_id

    prompt = "[Galaxy Bootstrap] Initialize persistent session for Hermes. Reply with exactly: READY"
    result = call_agent(prompt, server_url)
    new_session_id = _load_session_id()

    if new_session_id:
        log_event(
            "backend_session_created",
            component="hermes",
            session_id=new_session_id,
            reason="startup",
        )
    else:
        log_event(
            "backend_session_bootstrap_failed",
            component="hermes",
            detail=result[:200] if isinstance(result, str) else "unknown",
        )

    return new_session_id


def extract_agent_response(raw_output):
    """Extract readable text from opencode run output."""
    lines = raw_output.strip().split("\n")
    if not any(line.strip().startswith("{") for line in lines):
        return raw_output.strip()

    text_parts = []
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            # JSON format: text lives in data["part"]["text"]
            if "part" in data:
                part = data["part"]
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            elif "content" in data:
                text_parts.append(data["content"])
        except json.JSONDecodeError:
            continue

    if text_parts:
        return "\n".join(text_parts).strip()
    return raw_output[:2000].strip()


def write_response(order_id, order, payload, response_text):
    """Write response markdown file and return the path."""
    response_file = RESPONSE_DIR / ("galaxy-order-response-%s.md" % order_id)
    now = datetime.now(timezone.utc).isoformat()
    content = "# Galaxy Order Response\n\n"
    content += "**Order**: %s\n" % order.get("timestamp", "unknown")
    content += '**Message**: "%s"\n\n' % payload
    content += "---\n\n"
    content += response_text + "\n\n"
    content += "---\n\n"
    content += "*Hermes - %s*\n" % now
    response_file.write_text(content)
    return response_file


def archive_order(order_id, order, claimed_file):
    """Archive processed order."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    order["acknowledged"] = True
    order["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
    order["acknowledged_by"] = "Hermes"
    archive_file = ARCHIVE_DIR / ("%s.json" % order_id)
    archive_file.write_text(json.dumps(order, indent=2))
    claimed_file.unlink()


def send_notification(order_id, payload, response_text, chat_id=None):
    """Write outbox notification for Telegram relay. Full response included."""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    notification = {
        "type": "notification",
        "severity": "success",
        "from": "Hermes",
        "message": response_text,
        "order_payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sent": False,
    }
    if chat_id:
        notification["chat_id"] = chat_id
    outbox_file = OUTBOX_DIR / ("hermes-%s.json" % order_id)
    outbox_file.write_text(json.dumps(notification, indent=2))


# --- Heartbeat ---


def _get_machine_name():
    try:
        if GALAXY_CONFIG.exists():
            config = json.loads(GALAXY_CONFIG.read_text())
            return config.get("default_machine", "unknown")
    except (json.JSONDecodeError, OSError):
        pass
    return "unknown"


def update_heartbeat():
    session_id = _load_session_id()
    heartbeat = {
        "status": "running",
        "daemon": "hermes",
        "started_at": stats["started_at"],
        "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "last_poll_at": stats["last_poll_at"],
        "orders_processed": stats["orders_processed"],
        "failure_count": stats["failure_count"],
        "machine": _get_machine_name(),
        "session_id": session_id,
    }
    tmp = HEARTBEAT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(heartbeat, indent=2))
    tmp.rename(HEARTBEAT_FILE)


def clear_heartbeat():
    try:
        if HEARTBEAT_FILE.exists():
            heartbeat = json.loads(HEARTBEAT_FILE.read_text())
            heartbeat["status"] = "stopped"
            heartbeat["stopped_at"] = datetime.now(timezone.utc).isoformat()
            HEARTBEAT_FILE.write_text(json.dumps(heartbeat, indent=2))
    except (json.JSONDecodeError, OSError):
        pass


# --- Outbox: Activation/Deactivation ---


def notify_activation(interval):
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    machine = _get_machine_name()
    notification = {
        "type": "notification",
        "severity": "info",
        "from": "Hermes",
        "message": "Hermes Active - %s - every %ds" % (machine, interval),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sent": False,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    outbox_file = OUTBOX_DIR / ("hermes-activate-%s.json" % ts)
    outbox_file.write_text(json.dumps(notification, indent=2))


def notify_deactivation():
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    uptime = "unknown"
    if stats["started_at"]:
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(str(stats["started_at"]))
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        uptime = "%dh %dm" % (hours, minutes)
    processed = stats["orders_processed"]
    failed = stats["failure_count"]
    notification = {
        "type": "notification",
        "severity": "info",
        "from": "Hermes",
        "message": "Hermes Offline - %d delivered - %d failed - %s" % (processed, failed, uptime),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sent": False,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    outbox_file = OUTBOX_DIR / ("hermes-deactivate-%s.json" % ts)
    outbox_file.write_text(json.dumps(notification, indent=2))


# --- Main Loop ---


def main():
    parser = argparse.ArgumentParser(description="Hermes - Galaxy Messenger")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument(
        "--server",
        type=str,
        default="http://localhost:4096",
        help="OpenCode server URL",
    )
    args = parser.parse_args()

    print("Hermes - The Galaxy Messenger")
    print("Watching: %s" % ORDERS_DIR)
    print("Interval: %ds" % args.interval)
    print()

    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    CORRUPTED_DIR.mkdir(parents=True, exist_ok=True)

    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    log_event(
        "daemon_started",
        component="hermes",
        machine=_get_machine_name(),
        poll_interval_seconds=args.interval,
    )
    bootstrap_session(args.server)
    update_heartbeat()
    # notify_activation(args.interval)  # SILENCED: Only notify on errors

    print("Waiting for orders...\n")

    try:
        while running:
            stats["last_poll_at"] = datetime.now(timezone.utc).isoformat()

            if ORDERS_DIR.exists():
                for order_file in sorted(ORDERS_DIR.glob("*.json")):
                    if not running:
                        break
                    if order_file.suffix != ".json" or ".processing" in order_file.name:
                        continue
                    try:
                        data = json.loads(order_file.read_text())
                        if data.get("acknowledged", False):
                            continue
                    except json.JSONDecodeError:
                        print("Corrupted order: %s" % order_file.name)
                        corrupted_path = CORRUPTED_DIR / order_file.name
                        try:
                            order_file.rename(corrupted_path)
                        except OSError:
                            pass
                        continue
                    except OSError:
                        continue

                    print("Order: %s" % order_file.stem)
                    process_order(order_file, args.server)
                    print()

            update_heartbeat()

            for _ in range(args.interval * 2):
                if not running:
                    break
                time.sleep(0.5)

    except KeyboardInterrupt:
        pass

    processed = stats["orders_processed"]
    failed = stats["failure_count"]
    print("\n%d delivered - %d failed" % (processed, failed))
    log_event(
        "daemon_stopped",
        component="hermes",
        machine=_get_machine_name(),
        orders_processed=processed,
        failure_count=failed,
    )
    # notify_deactivation()  # SILENCED: Only notify on errors
    clear_heartbeat()


if __name__ == "__main__":
    main()
