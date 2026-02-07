# Galaxy Response Log

**Location**: `galaxy-protocol/.sisyphus/responses.jsonl`  
**Format**: JSONL (one JSON event per line)  
**Git**: Committed (queryable operational data)

## Purpose

Structured telemetry for Galaxy order execution. Replaces ephemeral `galaxy-order-response-*.md` files with queryable log.

## Event Schema

```json
{
  "timestamp": "2026-02-08T02:00:00.123456+00:00",
  "order_id": "telegram:1791247114",
  "channel": "telegram",
  "status": "delivered",
  "response_length": 234,
  "payload_length": 45,
  "error": null,
  "latency_ms": 4523
}
```

**Status values**: `delivered`, `failed`, `timeout`, `no_agent`

## Querying

Use the helper script for common queries:

```bash
# Recent responses
python3 tools/query-responses.py recent --limit 20

# Failures in last 24h
python3 tools/query-responses.py failures --hours 24

# Aggregate stats
python3 tools/query-responses.py stats

# Channel distribution
python3 tools/query-responses.py channels

# Latency percentiles
python3 tools/query-responses.py latency
```

## Manual Queries (jq)

```bash
# Failed orders today
cat galaxy-protocol/.sisyphus/responses.jsonl | \
  jq -r 'select(.status == "failed") | [.timestamp, .order_id, .error] | @tsv' | \
  grep $(date +%Y-%m-%d)

# Average latency by channel
cat galaxy-protocol/.sisyphus/responses.jsonl | \
  jq -s 'group_by(.channel) | map({channel: .[0].channel, avg_latency: (map(.latency_ms) | add / length)})'

# Error types distribution
cat galaxy-protocol/.sisyphus/responses.jsonl | \
  jq -r 'select(.error) | .error' | sort | uniq -c | sort -rn

# Hourly throughput
cat galaxy-protocol/.sisyphus/responses.jsonl | \
  jq -r '.timestamp[:13]' | uniq -c
```

## Log Rotation

When log exceeds 10MB, rotate manually:

```bash
cd galaxy-protocol/.sisyphus
mv responses.jsonl responses-$(date +%Y%m%d).jsonl
gzip responses-$(date +%Y%m%d).jsonl
```

Keep compressed archives for historical analysis.

## Debugging Workflow

1. **Order not delivered?**
   ```bash
   python3 tools/query-responses.py recent | grep {order_id}
   ```

2. **High failure rate?**
   ```bash
   python3 tools/query-responses.py failures --hours 6
   # Check error patterns
   ```

3. **Slow responses?**
   ```bash
   python3 tools/query-responses.py latency
   # P95 > 30s indicates agent timeout issues
   ```

4. **Channel issues?**
   ```bash
   python3 tools/query-responses.py channels
   # Verify telegram/web distribution
   ```

## Migration from .md Files

Old behavior (REMOVED):
- `galaxy-order-response-{id}.md` written to `.sisyphus/notepads/`
- Files accumulated indefinitely (20+ after a few days)
- No structured querying

New behavior (2026-02-08):
- Single `responses.jsonl` log file
- Auto-deleted after logging (no file sprawl)
- Queryable with jq or helper script
- Enables analytics and debugging

Old .md files already cleaned up (2026-02-08 housekeeping).
