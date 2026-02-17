"""HermesExecutor - Wraps existing hermes.py daemon via filesystem bridge."""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from caduceus.executors.base import Executor


class HermesExecutor(Executor):
    """Executor that delegates to existing hermes.py daemon.

    Uses the filesystem protocol:
    1. Write order JSON to .sisyphus/notepads/galaxy-orders/
    2. Wait for response file to appear
    3. Read response and return result

    This preserves the existing hermes.py daemon without modifications.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize HermesExecutor.

        Args:
            config: Configuration dict containing:
                - orders_dir (str): Path to orders directory
                - timeout (int): Max wait time for response (default: 600s)
                - poll_interval (float): How often to check for response (default: 1.0s)
        """
        self.orders_dir = Path(
            config.get("orders_dir", ".sisyphus/notepads/galaxy-orders")
        )
        self.notepads_dir = self.orders_dir.parent
        self.timeout = config.get("timeout", 600)  # 10 minutes
        self.poll_interval = config.get("poll_interval", 1.0)

        # Ensure orders directory exists
        self.orders_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Execute order via hermes.py filesystem bridge.

        Args:
            order: Order dict containing:
                - payload (str): The command to execute
                - timestamp (float): When order was created
                - order_id (str): Unique identifier

        Returns:
            Result dict containing:
                - success (bool): Whether execution succeeded
                - response_text (str): The response from hermes
                - error (str, optional): Error message if failed
        """
        order_id = order.get("order_id", f"order-{int(time.time())}")
        payload = order.get("payload", "")

        if not payload:
            return {"success": False, "response_text": "", "error": "Empty payload"}

        # Liveness notification paths (set up before try so finally can reference them)
        outbox_dir = self.notepads_dir / "galaxy-outbox"
        processing_notif = outbox_dir / f"processing-{order_id}.json"

        try:
            # Write order file
            order_file = self.orders_dir / f"{order_id}.json"
            order_file.write_text(
                json.dumps(
                    {
                        "payload": payload,
                        "timestamp": order.get("timestamp", time.time()),
                        "order_id": order_id,
                        **{
                            k: v
                            for k, v in order.items()
                            if k not in ["payload", "timestamp", "order_id"]
                        },
                    },
                    indent=2,
                )
            )

            # Signal 2: Processing acknowledgment — notify user order was picked up
            outbox_dir.mkdir(parents=True, exist_ok=True)
            processing_notif.write_text(json.dumps({
                "type": "notification",
                "severity": "info",
                "from": "Hermes",
                "order_id": order_id,
                "message": f"⏳ <b>Processing your order...</b>\n\n<code>{payload[:80]}</code>",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sent": False,
                "chat_id": order.get("chat_id"),
            }, indent=2))

            # Wait for response file
            response_file = self.notepads_dir / f"galaxy-order-response-{order_id}.md"
            start_time = time.time()
            last_heartbeat = start_time
            HEARTBEAT_INTERVAL = 60  # seconds — only for orders running >1 minute

            while time.time() - start_time < self.timeout:
                if response_file.exists():
                    # Read response
                    response_text = response_file.read_text()

                    # Clean up response file
                    try:
                        response_file.unlink()
                    except OSError:
                        pass

                    # Cleanup liveness notifications
                    try:
                        processing_notif.unlink(missing_ok=True)
                    except OSError:
                        pass
                    for hb in outbox_dir.glob(f"heartbeat-{order_id}-*.json"):
                        try:
                            hb.unlink(missing_ok=True)
                        except OSError:
                            pass

                    return {
                        "success": True,
                        "response_text": response_text,
                    }

                # Signal 3: Heartbeat every 60s after first minute
                elapsed = time.time() - start_time
                if elapsed >= HEARTBEAT_INTERVAL and (time.time() - last_heartbeat) >= HEARTBEAT_INTERVAL:
                    elapsed_min = int(elapsed // 60)
                    payload_preview = payload[:60]
                    hb_file = outbox_dir / f"heartbeat-{order_id}-{int(elapsed)}.json"
                    try:
                        hb_file.write_text(json.dumps({
                            "type": "notification",
                            "severity": "info",
                            "from": "Hermes",
                            "order_id": order_id,
                            "message": f"⏳ <b>Still working...</b> ({elapsed_min}m elapsed)\n\n<code>{payload_preview}</code>",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "sent": False,
                            "chat_id": order.get("chat_id"),
                        }, indent=2))
                    except OSError:
                        pass  # Heartbeat write failure is non-fatal
                    last_heartbeat = time.time()

                await asyncio.sleep(self.poll_interval)

            # Timeout - clean up order file if still exists
            if order_file.exists():
                try:
                    order_file.unlink()
                except OSError:
                    pass

            # Cleanup liveness notifications on timeout
            try:
                processing_notif.unlink(missing_ok=True)
            except OSError:
                pass
            for hb in outbox_dir.glob(f"heartbeat-{order_id}-*.json"):
                try:
                    hb.unlink(missing_ok=True)
                except OSError:
                    pass

            return {
                "success": False,
                "response_text": "",
                "error": f"Timeout after {self.timeout}s waiting for response",
            }

        except Exception as e:
            # Cleanup liveness notifications on error
            try:
                processing_notif.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                "success": False,
                "response_text": "",
                "error": f"Execution error: {str(e)}",
            }
