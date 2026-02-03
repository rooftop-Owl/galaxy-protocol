#!/usr/bin/env python3
"""
Galaxy Protocol Audit Trail

Logs all Galaxy operations to logs/galaxy-audit.jsonl for compliance and debugging.
Provides /audit command to query audit trail.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent  # project root (when loaded as submodule)
MODULE_ROOT = Path(__file__).parent.parent  # galaxy-protocol module root
AUDIT_LOG = REPO_ROOT / "logs/galaxy-audit.jsonl"


def log_event(event_type: str, data: dict, severity: str = "info"):
    """
    Append an event to the audit log.

    Args:
        event_type: Type of event (order_received, order_executed, health_check, etc.)
        data: Event-specific data
        severity: Event severity (info, warning, error, critical)
    """
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "severity": severity,
        **data,
    }

    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(event) + "\n")


def query_audit_log(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
):
    """
    Query the audit log with optional filters.

    Args:
        event_type: Filter by event type
        severity: Filter by severity level
        since: ISO timestamp - only return events after this time
        limit: Maximum number of events to return

    Returns:
        List of matching audit events
    """
    if not AUDIT_LOG.exists():
        return []

    events = []
    with open(AUDIT_LOG, "r") as f:
        for line in f:
            try:
                event = json.loads(line.strip())

                if event_type and event.get("event_type") != event_type:
                    continue

                if severity and event.get("severity") != severity:
                    continue

                if since and event.get("timestamp", "") < since:
                    continue

                events.append(event)

                if len(events) >= limit:
                    break

            except json.JSONDecodeError:
                continue

    return events[-limit:]


def print_audit_report(events):
    """Pretty print audit events."""
    if not events:
        print("No audit events found.")
        return

    print(f"\n{'=' * 80}")
    print(f"Galaxy Protocol Audit Report - {len(events)} events")
    print(f"{'=' * 80}\n")

    for event in events:
        timestamp = event.get("timestamp", "Unknown")
        event_type = event.get("event_type", "unknown")
        severity = event.get("severity", "info")

        severity_icon = {
            "critical": "🚨",
            "error": "❌",
            "warning": "⚠️",
            "info": "ℹ️",
            "success": "✅",
        }.get(severity, "•")

        print(f"{severity_icon} [{timestamp}] {event_type.upper()}")

        for key, value in event.items():
            if key not in ["timestamp", "event_type", "severity"]:
                print(f"  {key}: {value}")

        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Galaxy Protocol Audit Trail")
    parser.add_argument("--type", help="Filter by event type")
    parser.add_argument(
        "--severity", help="Filter by severity (info, warning, error, critical)"
    )
    parser.add_argument("--since", help="Show events since timestamp (ISO 8601)")
    parser.add_argument("--limit", type=int, default=100, help="Maximum events to show")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    events = query_audit_log(
        event_type=args.type, severity=args.severity, since=args.since, limit=args.limit
    )

    if args.json:
        print(json.dumps(events, indent=2))
    else:
        print_audit_report(events)


if __name__ == "__main__":
    main()
