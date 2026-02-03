---
deployable: true
version: 1.0.0
---

# Galaxy Orders Protocol

**Purpose**: Enable cross-machine command relay via Telegram Galaxy bot.  
**Status**: Active  

## Overview

The Galaxy bot writes orders to `.sisyphus/notepads/galaxy-orders/*.json`.
Agents check for unacknowledged orders at session start and process them.

## 1. Session Start Protocol

**When**: Every session start (after Stargazer findings check)  
**What**: Scan for unacknowledged orders

### Detection Steps

1. **Scan Directory**: `.sisyphus/notepads/galaxy-orders/*.json`
2. **Filter**: Find orders where `"acknowledged": false`
3. **Present**: Summarize to user before proceeding with main request
4. **Non-Blocking**: User decides whether to execute

### Presentation Format

```
📡 **Galaxy Order Received**

From: {from_field}
Target: {machine_name}
Timestamp: {iso8601_timestamp}
Order: "{payload_text}"

Execute this order? (yes/no)
```

## 2. Order Processing Protocol

**When**: User approves order execution  
**What**: Execute → Respond → Acknowledge → Archive

### Processing Steps

1. **Execute**: Perform the requested action
2. **Write Response**: Create `.sisyphus/notepads/galaxy-order-response-{timestamp}.md`
3. **Update Order**: Set `"acknowledged": true` in original JSON file
4. **Archive**: Move to `.sisyphus/notepads/galaxy-orders-archive/{original-filename}`

### Response File Format

```markdown
# Galaxy Order Response

**Order Received**: {timestamp_utc}  
**Message**: "{payload}"  
**Acknowledged By**: {agent_name} ({session_type})

---

## Response

{detailed_response_content}

---

**{Agent Name}**  
{Session Type}  
{date}
```

### Acknowledgment Update

Original order JSON file gets modified:

```json
{
  "type": "galaxy_order",
  "from": "galaxy-gazer",
  "target": "machine_name",
  "command": "general",
  "payload": "order text",
  "timestamp": "2026-02-02T06:25:57.320440+00:00",
  "acknowledged": true,
  "acknowledged_at": "2026-02-02T12:30:00.000000+00:00",
  "acknowledged_by": "Sisyphus (Main Session)"
}
```

### Archiving

```bash
# Create archive directory if needed
mkdir -p .sisyphus/notepads/galaxy-orders-archive/

# Move acknowledged order
mv .sisyphus/notepads/galaxy-orders/{timestamp}.json \
   .sisyphus/notepads/galaxy-orders-archive/
```

## 3. Outbox Protocol (Agent → Galaxy)

**Purpose**: Agents can proactively send notifications to Telegram  
**When**: Agent needs to alert user outside normal session flow

### Outbox Message Schema

Location: `.sisyphus/notepads/galaxy-outbox/*.json`

```json
{
  "type": "notification",
  "severity": "info|warning|critical|success|alert",
  "from": "{agent_name}",
  "message": "{notification_text}",
  "timestamp": "{iso8601}",
  "sent": false
}
```

### Writing Outbox Messages

```bash
# Create outbox directory if needed
mkdir -p .sisyphus/notepads/galaxy-outbox/

# Write notification
cat > .sisyphus/notepads/galaxy-outbox/$(date +%Y%m%d-%H%M%S).json <<EOF
{
  "type": "notification",
  "severity": "high",
  "from": "Sisyphus",
  "message": "Build failed after 3 retry attempts. Manual intervention required.",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%6N%z)",
  "sent": false
}
EOF
```

**Note**: Galaxy bot polls this directory and sends messages to Telegram automatically.

## 4. Standby Mode Protocol

**Purpose**: Continuous polling mode for auto-processing Galaxy orders  
**When**: Agent runs `/galaxy-standby` command in dedicated TUI session  
**Command**: `.claude/commands/galaxy-standby.md`

### Overview

Standby mode creates a dedicated agent session that continuously monitors `galaxy-orders/*.json` and auto-executes unacknowledged orders without user intervention between orders. Unlike Session Start detection (Section 1) which asks for user approval, standby mode auto-approves all orders.

### When to Use

| Mode | Use Case |
|------|----------|
| **Session Start** | Normal work sessions — orders presented for manual approval |
| **Standby Mode** | Dedicated monitoring — orders auto-executed without prompts |

### Activation

```bash
opencode /galaxy-standby [--interval <seconds>]

# Default: 30-second polling interval
# Matches bot's outbox polling frequency
```

### Standby Loop Behavior

1. **Poll**: Check `galaxy-orders/*.json` every N seconds (default 30)
2. **Detect**: Find orders where `acknowledged: false`
3. **Auto-Execute**: Process payload as natural language instruction (no user prompt)
4. **Respond**: Write response file per Section 2 format
5. **Acknowledge**: Set `acknowledged: true`, add metadata
6. **Archive**: Move to `galaxy-orders-archive/`
7. **Notify**: Write outbox notification for Telegram relay
8. **Repeat**: Continue until user types anything to exit

### Standby vs Session Start Differences

| Aspect | Session Start (§1) | Standby Mode (§4) |
|--------|-------------------|-------------------|
| **Trigger** | Every new session | Dedicated `/galaxy-standby` command |
| **Approval** | User must confirm | Auto-execute (no prompts) |
| **Frequency** | Once per session start | Continuous polling loop |
| **Exit** | Proceeds to main request | User types anything to exit |
| **Use Case** | Ad-hoc order processing | Dedicated monitoring session |

### Outbox Notifications

Standby mode writes three types of notifications:

**Activation**:
```json
{
  "type": "notification",
  "severity": "info",
  "from": "Sisyphus (Standby)",
  "message": "🟢 Standby Mode Activated on <code>{machine}</code>",
  "timestamp": "{iso8601}",
  "sent": false
}
```

**Execution** (per order):
```json
{
  "type": "notification",
  "severity": "success",
  "from": "Sisyphus (Standby)",
  "message": "✅ Order Executed: <code>{payload_summary}</code>",
  "timestamp": "{iso8601}",
  "sent": false
}
```

**Deactivation**:
```json
{
  "type": "notification",
  "severity": "info",
  "from": "Sisyphus (Standby)",
  "message": "🔴 Standby Deactivated. Processed {count} orders.",
  "timestamp": "{iso8601}",
  "sent": false
}
```

### Phase 2.7 Limitations

Current implementation (Phase 2.7) is single-machine only:

- ❌ **NO machine identity filtering** — processes all orders regardless of `target` field
- ❌ **NO session locking** — assumes single standby session per machine
- ❌ **NO conflict detection** — no coordination between multiple standbys
- ⚠️ **Session compaction risk** — long-running sessions accumulate context and may drift after 10-20 orders

These are intentional limitations. Phase C (MCP server + opencode CLI) addresses them.

### Error Handling

If order execution fails:
1. Log failure in response file
2. Set `acknowledged: true` (prevents infinite retries)
3. Archive with failure note
4. Write outbox notification with `severity: "warning"`
5. Continue to next order (don't block on failures)

## 5. Phase C: MCP Server Protocol

**Purpose**: Eliminate session compaction via fresh agent sessions per order  
**When**: Production multi-machine deployment with high order volume  
**Architecture**: MCP server + opencode CLI integration

### Overview

Phase C replaces the long-running standby session with an MCP server that spawns fresh `opencode run --attach` sessions for each order. This eliminates context accumulation and session drift.

### Architecture Layers

```
Layer 1: opencode serve --port 4096       → persistent agent backend (one-time boot)
Layer 2: Galaxy MCP server                → watches orders/, exposes tools (no compaction)
Layer 3: opencode run --attach :4096      → per-order agent execution (full reasoning)
Layer 4: galaxy-gazer bot                 → Telegram ↔ filesystem (unchanged)
```

### MCP Server Implementation

**File**: `tools/galaxy/galaxy_mcp.py`  
**Framework**: FastMCP (lifespan background tasks)  
**Pattern**: MCPtrace-style background watcher loop

### MCP Tools

| Tool | Purpose | Parameters |
|------|---------|------------|
| `galaxy_poll()` | Check for unacknowledged orders | None |
| `galaxy_execute(order_id, payload)` | Execute order via `opencode run --attach` | `order_id`, `payload` |
| `galaxy_acknowledge(order_id)` | Mark order as acknowledged, archive | `order_id` |
| `galaxy_status()` | Get server status, processed count | None |

### Background Tasks

**Order Watcher Loop**:
- Polls `galaxy-orders/*.json` every 30 seconds (configurable)
- Detects `acknowledged: false` orders
- Auto-executes via `opencode run --attach http://localhost:4096`
- Writes response, acknowledges, archives per Section 2 protocol
- Continues indefinitely until server shutdown

**Response Cleanup**:
- Archives response files older than 30 days (configurable)
- Prevents `.sisyphus/notepads/` from growing unbounded

### Execution Flow

1. **Order Arrives**: Bot writes `galaxy-orders/{timestamp}.json`
2. **MCP Detects**: Background watcher finds `acknowledged: false`
3. **Spawn Session**: `opencode run --attach :4096 "Execute: {payload}"`
4. **Fresh Context**: New agent session with full reasoning capability
5. **Write Response**: Agent writes `.sisyphus/notepads/galaxy-order-response-{timestamp}.md`
6. **Acknowledge**: MCP updates order JSON, archives to `galaxy-orders-archive/`
7. **Notify**: Write outbox notification for Telegram relay
8. **Loop**: Return to step 2

### Configuration

**MCP Server Config** (`.mcp.json`):
```json
{
  "mcpServers": {
    "galaxy": {
      "command": "python3",
      "args": ["tools/galaxy/galaxy_mcp.py"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      },
      "description": "Galaxy Protocol MCP server - auto-execute Telegram bot orders"
    }
  }
}
```

**Environment Variables** (optional):
- `GALAXY_POLL_INTERVAL`: Seconds between order checks (default: 30)
- `GALAXY_RESPONSE_RETENTION_DAYS`: Days to keep response files (default: 30)
- `OPENCODE_ATTACH_URL`: URL for `opencode run --attach` (default: `http://localhost:4096`)

### Deployment

**Prerequisites**:
1. Install dependencies: `pip install -r tools/galaxy/requirements.txt`
2. Start opencode backend: `opencode serve --port 4096` (systemd recommended)
3. Verify MCP discovery: `opencode mcp list` (should show "galaxy")

**Systemd Service** (`tools/galaxy/galaxy-mcp.service`):
```ini
[Unit]
Description=Galaxy MCP Server (Phase C)
After=network.target

[Service]
Type=simple
User=zephyr
WorkingDirectory=/home/zephyr/astraeus
ExecStart=/usr/bin/python3 tools/galaxy/galaxy_mcp.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**Enable**:
```bash
sudo cp tools/galaxy/galaxy-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable galaxy-mcp
sudo systemctl start galaxy-mcp
```

### Phase C vs Phase 2.7 Comparison

| Aspect | Phase 2.7 (Standby) | Phase C (MCP Server) |
|--------|---------------------|----------------------|
| **Session Type** | Single long-running | Fresh per order |
| **Context Limit** | Compaction after 10-20 orders | No limit (fresh context) |
| **Reasoning Quality** | Degrades over time | Consistent (full agent) |
| **Resource Usage** | Low (one session) | Higher (spawn per order) |
| **Failure Recovery** | Manual restart | Auto-retry via fresh session |
| **Multi-Machine** | No filtering | Can add filtering logic |
| **Production Ready** | No (drift risk) | Yes (designed for scale) |

### Testing

**Local Test**:
```bash
# Terminal 1: Start opencode backend
opencode serve --port 4096

# Terminal 2: Start MCP server
python3 tools/galaxy/galaxy_mcp.py

# Terminal 3: Verify discovery
opencode mcp list  # Should show "galaxy"

# Terminal 4: Send test order via Telegram
# (or manually write galaxy-orders/{timestamp}.json)

# Watch Terminal 2 for execution logs
```

**E2E Test**:
1. Send order via Telegram bot
2. Verify MCP server detects it (check logs)
3. Verify `opencode run --attach` executes (check logs)
4. Verify response file written: `.sisyphus/notepads/galaxy-order-response-*.md`
5. Verify order archived: `galaxy-orders-archive/{timestamp}.json`
6. Verify Telegram notification sent (check bot logs)

### Migration from Phase 2.7

**Backward Compatible**: Phase 2.7 `/galaxy-standby` command remains functional.

**Migration Steps**:
1. Deploy Phase C MCP server (systemd service)
2. Stop Phase 2.7 standby sessions (`Ctrl+C` or `kill`)
3. Verify MCP server processing orders
4. Keep `/galaxy-standby` available for manual/emergency use

**Rollback**: Stop MCP server systemd service, restart `/galaxy-standby` session.

## Anti-Patterns

❌ **DO NOT** block session on order processing (Session Start mode only)  
❌ **DO NOT** execute orders without user approval (Session Start mode only — Standby/MCP auto-execute by design)  
❌ **DO NOT** modify order JSON schema (tested with 67 tests)  
❌ **DO NOT** skip archiving (causes re-processing)  
❌ **DO NOT** create orders from agents (use outbox instead)  
❌ **DO NOT** use Phase 2.7 standby for production high-volume scenarios (use Phase C MCP server)

## Integration with Existing Systems

- **Stargazer Findings**: Same pattern, different directory
- **Boulder.json**: Independent - orders don't affect active plan tracking
- **Git Workflow**: Order responses are committable artifacts
- **Multi-Machine**: Orders target specific machines via `"target"` field

## Testing

Verify with existing test suite:
```bash
python3 -m pytest tests/test_galaxy_bot.py -v
# Expected: 67 passed
```

## Deployment

This rule file is marked `deployable: true` and will be deployed to child projects via:
```bash
python3 tools/astraeus load --target /path/to/child
```
