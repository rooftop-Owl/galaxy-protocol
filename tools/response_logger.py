#!/usr/bin/env python3
"""
Response Logger - Structured telemetry for Galaxy order execution.

Appends JSONL events to galaxy-protocol/.sisyphus/responses.jsonl for:
- Debugging delivery failures
- Analyzing latency patterns
- Channel usage distribution
- Error type classification

Never gitignored despite being in .sisyphus - this is queryable operational data.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# Log location: module-scoped, not parent repo
MODULE_ROOT = Path(__file__).parent.parent
RESPONSE_LOG = MODULE_ROOT / ".sisyphus/responses.jsonl"


def log_response(
    order_id,
    status,
    response_text=None,
    error=None,
    channel="telegram",
    latency_ms=None,
    payload=None
):
    """
    Append response event to structured log.
    
    Args:
        order_id: Unique order identifier
        status: delivered | failed | timeout | no_agent
        response_text: Agent response (optional, length recorded)
        error: Error message if status != delivered
        channel: telegram | web | whatsapp | etc
        latency_ms: Execution time in milliseconds
        payload: Original order text (optional, length recorded)
    """
    RESPONSE_LOG.parent.mkdir(parents=True, exist_ok=True)
    
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "order_id": order_id,
        "channel": channel,
        "status": status,
        "response_length": len(response_text) if response_text else 0,
        "payload_length": len(payload) if payload else 0,
        "error": error,
        "latency_ms": latency_ms
    }
    
    with open(RESPONSE_LOG, "a") as f:
        f.write(json.dumps(event) + "\n")


def query_recent(limit=10):
    """Read last N events (for debugging)."""
    if not RESPONSE_LOG.exists():
        return []
    
    with open(RESPONSE_LOG) as f:
        lines = f.readlines()
    
    return [json.loads(line) for line in lines[-limit:]]


def query_failures(since_hours=24):
    """Get failed orders in last N hours."""
    if not RESPONSE_LOG.exists():
        return []
    
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    
    failures = []
    with open(RESPONSE_LOG) as f:
        for line in f:
            event = json.loads(line)
            if event["status"] == "failed":
                event_time = datetime.fromisoformat(event["timestamp"])
                if event_time > cutoff:
                    failures.append(event)
    
    return failures


def stats_summary():
    """Aggregate stats for health check."""
    if not RESPONSE_LOG.exists():
        return {"total": 0, "delivered": 0, "failed": 0}
    
    counts = {"total": 0, "delivered": 0, "failed": 0, "timeout": 0}
    latencies = []
    
    with open(RESPONSE_LOG) as f:
        for line in f:
            event = json.loads(line)
            counts["total"] += 1
            counts[event["status"]] = counts.get(event["status"], 0) + 1
            if event.get("latency_ms"):
                latencies.append(event["latency_ms"])
    
    stats = {
        "total_orders": counts["total"],
        "delivered": counts["delivered"],
        "failed": counts["failed"],
        "success_rate": counts["delivered"] / counts["total"] if counts["total"] > 0 else 0,
    }
    
    if latencies:
        stats["avg_latency_ms"] = sum(latencies) / len(latencies)
        stats["p95_latency_ms"] = sorted(latencies)[int(len(latencies) * 0.95)]
    
    return stats
