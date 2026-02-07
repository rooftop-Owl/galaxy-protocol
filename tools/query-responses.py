#!/usr/bin/env python3
"""
Query Galaxy response log - debugging and analytics helper.

Usage:
    python3 tools/query-responses.py recent [--limit 20]
    python3 tools/query-responses.py failures [--hours 24]
    python3 tools/query-responses.py stats
    python3 tools/query-responses.py channels
    python3 tools/query-responses.py latency
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import Counter

MODULE_ROOT = Path(__file__).parent.parent
RESPONSE_LOG = MODULE_ROOT / ".sisyphus/responses.jsonl"


def load_events():
    """Load all events from log."""
    if not RESPONSE_LOG.exists():
        return []
    with open(RESPONSE_LOG) as f:
        return [json.loads(line) for line in f]


def cmd_recent(args):
    """Show recent responses."""
    events = load_events()[-args.limit:]
    if not events:
        print("No responses logged yet")
        return
    
    for e in events:
        status_icon = "✓" if e["status"] == "delivered" else "✗"
        print(f"{status_icon} {e['timestamp'][:19]} {e['order_id'][:20]:<20} {e['status']:<10} {e.get('latency_ms', 0):>6}ms")


def cmd_failures(args):
    """Show failed orders."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    events = load_events()
    
    failures = [e for e in events 
                if e["status"] == "failed" 
                and datetime.fromisoformat(e["timestamp"]) > cutoff]
    
    if not failures:
        print(f"No failures in last {args.hours} hours")
        return
    
    print(f"Found {len(failures)} failures in last {args.hours} hours:\n")
    for e in failures:
        print(f"⚠ {e['timestamp'][:19]} {e['order_id']}")
        print(f"  Error: {e.get('error', 'Unknown')}\n")


def cmd_stats(args):
    """Show aggregate statistics."""
    events = load_events()
    if not events:
        print("No responses logged yet")
        return
    
    status_counts = Counter(e["status"] for e in events)
    latencies = [e["latency_ms"] for e in events if e.get("latency_ms")]
    
    print(f"Total orders: {len(events)}")
    print(f"Delivered: {status_counts.get('delivered', 0)}")
    print(f"Failed: {status_counts.get('failed', 0)}")
    print(f"Success rate: {status_counts.get('delivered', 0) / len(events) * 100:.1f}%")
    
    if latencies:
        print(f"\nLatency:")
        print(f"  Avg: {sum(latencies) / len(latencies):.0f}ms")
        print(f"  P50: {sorted(latencies)[len(latencies) // 2]:.0f}ms")
        print(f"  P95: {sorted(latencies)[int(len(latencies) * 0.95)]:.0f}ms")
        print(f"  Max: {max(latencies):.0f}ms")


def cmd_channels(args):
    """Show channel distribution."""
    events = load_events()
    if not events:
        print("No responses logged yet")
        return
    
    channel_counts = Counter(e.get("channel", "unknown") for e in events)
    print("Channel distribution:")
    for channel, count in channel_counts.most_common():
        print(f"  {channel}: {count}")


def cmd_latency(args):
    """Show latency breakdown by percentile."""
    events = load_events()
    latencies = [e["latency_ms"] for e in events if e.get("latency_ms")]
    
    if not latencies:
        print("No latency data available")
        return
    
    sorted_lat = sorted(latencies)
    percentiles = [10, 25, 50, 75, 90, 95, 99]
    
    print("Latency percentiles:")
    for p in percentiles:
        idx = int(len(sorted_lat) * (p / 100))
        print(f"  P{p:>2}: {sorted_lat[idx]:>6.0f}ms")


def main():
    parser = argparse.ArgumentParser(description="Query Galaxy response log")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    recent = subparsers.add_parser("recent", help="Show recent responses")
    recent.add_argument("--limit", type=int, default=10, help="Number of events to show")
    
    failures = subparsers.add_parser("failures", help="Show failed orders")
    failures.add_argument("--hours", type=int, default=24, help="Time window in hours")
    
    subparsers.add_parser("stats", help="Show aggregate statistics")
    subparsers.add_parser("channels", help="Show channel distribution")
    subparsers.add_parser("latency", help="Show latency breakdown")
    
    args = parser.parse_args()
    
    if args.command == "recent":
        cmd_recent(args)
    elif args.command == "failures":
        cmd_failures(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "channels":
        cmd_channels(args)
    elif args.command == "latency":
        cmd_latency(args)


if __name__ == "__main__":
    main()
