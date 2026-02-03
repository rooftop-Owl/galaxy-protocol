# Galaxy Protocol — Demo and Setup Guide

Control AI agents from your phone. Send commands via Telegram, agents process them on remote machines, responses arrive back on your phone. Zero human intervention.

## Architecture

```
Phone (Telegram app)
    ↓
Telegram Bot (galaxy-gazer)
    ↓
Filesystem (.sisyphus/notepads/galaxy-orders/*.json)
    ↓
Galaxy MCP Server (watches orders)
    ↓
opencode run --attach (fresh agent per order)
    ↓
Response (.sisyphus/notepads/galaxy-order-response-*.md)
    ↓
Outbox notification
    ↓
Back to Phone
```

**Key Features**:
- **Fresh context per order**: No compaction, no session drift
- **Multi-machine**: Control multiple servers from one bot
- **Production-ready**: Security hardening, error recovery, atomic operations
- **Bidirectional**: Agents can send unsolicited notifications via outbox

---

## One-Time Setup

### 1. Create Telegram Bot

1. On Telegram, message [@BotFather](https://t.me/BotFather)
2. Send: `/newbot`
3. Choose a name: `galaxy-gazer-demo` (or your choice)
4. Choose a username: `your_galaxy_bot` (must end in `bot`)
5. **Save the token** — looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### 2. Get Your Telegram User ID

1. On Telegram, message [@userinfobot](https://t.me/userinfobot)
2. Send: `/start`
3. **Save your user ID** — a number like `123456789`

### 3. Configure Galaxy

```bash
cd /path/to/your/astraeus-project

# Create config from template
cp tools/galaxy/config.json.example .galaxy/config.json

# Edit configuration
nano .galaxy/config.json
```

**Minimum configuration** (local machine only):

```json
{
  "telegram_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
  "authorized_users": [123456789],
  "default_machine": "local",
  "machines": {
    "local": {
      "repo_path": "/home/user/your-project",
      "type": "local"
    }
  }
}
```

**Multi-machine configuration** (with remote SSH):

```json
{
  "telegram_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
  "authorized_users": [123456789, 987654321],
  "default_machine": "local",
  "machines": {
    "local": {
      "repo_path": "/home/user/astraeus",
      "type": "local"
    },
    "remote-server": {
      "repo_path": "/home/deploy/astraeus",
      "type": "remote",
      "host": "192.168.1.100",
      "ssh_user": "deploy"
    }
  }
}
```

**Configuration fields**:
- `telegram_token`: Bot token from @BotFather
- `authorized_users`: Array of Telegram user IDs (only these users can control the bot)
- `default_machine`: Default target for single-machine commands
- `machines`: Dictionary of machine configs (local or remote via SSH)

### 4. Install Dependencies

```bash
cd /path/to/your/project
pip install -r tools/galaxy/requirements.txt

# Installs:
# - python-telegram-bot>=20.0,<22.0
# - fastmcp>=0.1.0
```

---

## Running the Demo

### Option A: Phase C (Production - Recommended)

**Best for**: Production deployments, high-volume orders, multiple concurrent requests

**Start services** (3 terminals):

**Terminal 1 — OpenCode Server** (persistent agent brain):
```bash
cd /path/to/your/project
opencode serve --port 4096
```

**Terminal 2 — Galaxy MCP Server** (order watcher):
```bash
cd /path/to/your/project
python3 tools/galaxy/galaxy_mcp.py
```

**Terminal 3 — Telegram Bot** (phone relay):
```bash
cd /path/to/your/project
python3 tools/galaxy/bot.py
```

**How it works**:
- `opencode serve`: Persistent backend, stays running
- Galaxy MCP: Watches `.sisyphus/notepads/galaxy-orders/` every 5 seconds
- When order detected: spawns `opencode run --attach http://localhost:4096 "<order>"`
- Fresh agent session per order = no compaction, consistent quality

---

### Option B: Phase 2.7 (Manual Standby Mode)

**Best for**: Testing, development, low-resource environments

**Terminal 1 — Telegram Bot**:
```bash
cd /path/to/your/project
python3 tools/galaxy/bot.py
```

**Terminal 2 — OpenCode Standby Session**:
```bash
cd /path/to/your/project
opencode
```

Inside the OpenCode session:
```
/galaxy-standby
```

Agent enters polling loop (checks every 30s for new orders).

**Limitation**: Single long-running session processes all orders. After many orders (~50+), context compaction may degrade quality. Exit and restart `/galaxy-standby` to reset.

---

## Demo Commands

### Basic Commands

#### Check Machine Status

**On phone** (Telegram):
```
/status
```

**Response**:
```
🎯 Machine: local

📊 Git Status:
(clean)

📝 Recent Commits:
4c1ba0d Merge feat/galaxy-phase2-multi-machine
8cca754 fix: pin oh-my-opencode
f161ae9 fix(galaxy): security improvements

🌟 Stargazer Findings: 0
📬 Galaxy Orders: 0 pending
```

#### Send an Order

**On phone**:
```
/order Hello from my phone!
```

**What happens**:
1. Bot writes order to `.sisyphus/notepads/galaxy-orders/TIMESTAMP.json`
2. MCP server detects new order (or standby session polls)
3. Agent processes order with full reasoning
4. Response written to `.sisyphus/notepads/galaxy-order-response-TIMESTAMP.md`
5. Bot sends response back to phone

**Response** (appears in 5-30 seconds):
```
✅ Order Acknowledged

📍 local
📨 Hello from my phone!

[Agent's natural language response here]
```

#### Multi-Machine Status

**On phone**:
```
/status all
```

Queries all machines in parallel, returns consolidated status.

#### List Machines

**On phone**:
```
/machines
```

**Response**:
```
🖥️ Registered Machines:

local (default)
  Type: local
  Path: /home/user/astraeus

remote-server
  Type: remote (SSH)
  Host: deploy@192.168.1.100
  Path: /home/deploy/astraeus
```

---

## Demo Scenarios

### 1. "I Am Your Father" (Star Wars Reference)

**Test agent's contextual understanding**:

**On phone**:
```
/order I... am your father...
```

**Expected response**:
```
NOOOOOOO! That's not true! That's impossible!
```

Agent recognizes the Star Wars reference and plays along. (Actual response from production testing — see `.sisyphus/JOURNAL.md` entry "I Am Your Father".)

---

### 2. File Creation Task

**On phone**:
```
/order Create a file called hello.txt with the text "Hello from Galaxy Protocol"
```

**Agent will**:
1. Understand the instruction
2. Execute: `echo "Hello from Galaxy Protocol" > hello.txt`
3. Verify: check file exists
4. Respond with confirmation

**Response**:
```
✅ Order Acknowledged

📍 local
📨 Create a file called hello.txt...

File created successfully at ./hello.txt with content:
"Hello from Galaxy Protocol"
```

---

### 3. Cross-Machine Order

**On phone**:
```
/order remote-server Check disk space
```

**Agent will**:
1. SSH to remote-server (if configured)
2. Run: `df -h`
3. Parse output
4. Send formatted response

---

### 4. Stargazer Concerns

**On phone**:
```
/concerns
```

If you've run `/stargazer` in another session and concerns were flagged, bot sends them to your phone.

---

## Monitoring

### Watch Order Flow (Real-Time)

**Terminal 4**:
```bash
cd /path/to/your/project
watch -n 1 'echo "=== PENDING ===" && ls -lh .sisyphus/notepads/galaxy-orders/ && echo "=== PROCESSED ===" && ls -lh .sisyphus/notepads/galaxy-orders-archive/ | tail -5'
```

Shows:
- **Pending**: Unacknowledged orders waiting for processing
- **Processed**: Archived orders with timestamps

### Watch Responses

**Terminal 5**:
```bash
watch -n 1 'ls -lht .sisyphus/notepads/galaxy-order-response-*.md | head -5'
```

Shows the 5 most recent response files.

### Check MCP Server Status

**In OpenCode session with Galaxy MCP enabled**:
```python
from mcp import use_mcp_tool

result = await use_mcp_tool("galaxy", "galaxy_status")
print(result)
```

**Output**:
```json
{
  "machine": "local",
  "uptime_seconds": 3600,
  "uptime_human": "1h 0m",
  "processed": 12,
  "failed": 0,
  "pending": 0,
  "opencode_server": "http://localhost:4096",
  "opencode_healthy": true
}
```

---

## Troubleshooting

### Bot Not Responding

**Symptom**: Send `/status` on phone, no response

**Check**:
```bash
# Verify bot is running
ps aux | grep bot.py

# Check bot logs
python3 tools/galaxy/bot.py
# Should see: "Bot started. Polling for messages..."
```

**Fix**:
1. Verify `telegram_token` in `.galaxy/config.json` is correct
2. Verify your user ID is in `authorized_users` array
3. Restart bot after config changes

---

### Orders Not Processing

**Symptom**: Send `/order <msg>`, bot confirms, but no response arrives

**Check Phase C**:
```bash
# 1. Check MCP server running
ps aux | grep galaxy_mcp.py

# 2. Check opencode serve running
curl http://localhost:4096/health
# Should return: 200 OK

# 3. Check for orphaned orders
ls -la .sisyphus/notepads/galaxy-orders/
# If *.json files exist but not processing, MCP server is down
```

**Check Phase 2.7**:
```bash
# Verify standby session is in polling loop
# Should see console output: "Polling for orders... (interval: 30s)"
```

**Fix**:
1. Restart `opencode serve --port 4096`
2. Restart `python3 tools/galaxy/galaxy_mcp.py`
3. Check MCP server logs for errors

---

### "Not authorized" Error

**Symptom**: Bot responds: "⛔ Not authorized"

**Fix**:
```bash
# 1. Get your Telegram user ID
# Message @userinfobot on Telegram

# 2. Add to config
nano .galaxy/config.json
# Add your ID to "authorized_users": [123456789]

# 3. Restart bot
# Kill old bot (Ctrl+C), restart:
python3 tools/galaxy/bot.py
```

---

### Orders Stuck in .processing State

**Symptom**: Files named `*.json.processing` exist in galaxy-orders/

**Cause**: Agent execution timed out or crashed before completion

**Fix**:
```bash
cd .sisyphus/notepads/galaxy-orders/

# Restore processing files to retry
for f in *.json.processing; do
  mv "$f" "${f%.processing}"
done

# Or delete if order is no longer relevant
rm *.json.processing
```

---

## Production Deployment (systemd)

For 24/7 operation, deploy as systemd services.

### Galaxy MCP Service

```bash
# Copy service file
sudo cp tools/galaxy/galaxy-mcp.service /etc/systemd/system/

# Edit paths in service file
sudo nano /etc/systemd/system/galaxy-mcp.service
# Update: WorkingDirectory, ExecStart paths, User

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable galaxy-mcp
sudo systemctl start galaxy-mcp

# Check status
sudo systemctl status galaxy-mcp
```

### Telegram Bot Service

```bash
sudo cp tools/galaxy/galaxy.service /etc/systemd/system/

# Edit paths
sudo nano /etc/systemd/system/galaxy.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable galaxy
sudo systemctl start galaxy

# Check logs
sudo journalctl -u galaxy -f
```

### OpenCode Serve Service

Create `/etc/systemd/system/opencode-serve.service`:

```ini
[Unit]
Description=OpenCode Server for Galaxy Protocol
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/astraeus
ExecStart=/usr/local/bin/opencode serve --port 4096
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable opencode-serve
sudo systemctl start opencode-serve
```

---

## Security Considerations

### Authorized Users

Only Telegram users in `authorized_users` can send commands. The bot **will not respond** to unauthorized users.

**Verify**:
```bash
# Bot logs show unauthorized attempts:
# [Auth] User 999999999 not authorized (denied)
```

### SSH Security

For remote machines:
1. Use SSH key authentication (not passwords)
2. Restrict SSH user permissions (read-only git, limited sudo)
3. Consider SSH jump hosts for production servers

### Order Payload Validation

Phase C hardening includes:
- **Max payload length**: 10,000 characters (prevents DoS)
- **Empty payload rejection**: Orders must have content
- **Command injection prevention**: All SSH args quoted with `shlex.quote()`

### Secrets in Orders

**Warning**: Do NOT send secrets via `/order` commands. Orders are written to plaintext JSON files.

**Safe**:
```
/order Check environment variable DATABASE_URL
```

**Unsafe**:
```
/order Set DATABASE_URL to postgres://user:SECRET_PASSWORD@host/db
```

---

## 5-Minute Demo Script

**Prep** (30 seconds):
- Start all 3 services: `opencode serve`, `galaxy_mcp.py`, `bot.py`

**Demo** (4.5 minutes):

1. **Introduction** (30s):
   - "Control AI agents from your phone"
   - Show Telegram app on phone

2. **Status Check** (1m):
   - Send: `/status`
   - Explain: "Bot → filesystem → agent → response"
   - Response appears in 5-10 seconds

3. **Simple Order** (1m):
   - Send: `/order What's 2+2?`
   - Show response: "4"
   - "Agent processed natural language, computed, responded"

4. **Wow Moment** (1m):
   - Send: `/order I am your father`
   - Show Star Wars reference response
   - "Agent has context, personality, reasoning"

5. **Architecture** (1m):
   - Show terminals: 4 layers, each stateless
   - Show `.sisyphus/notepads/` files appearing/disappearing
   - "Fresh agent per order = no drift, production-ready"

**Conclusion**:
"You just commanded an AI from your phone. It's secure, multi-machine capable, and production-ready."

---

## Next Steps

### Multi-Machine Setup

1. Add remote machines to `.galaxy/config.json`
2. Set up SSH key authentication
3. Deploy astraeus to remote machines
4. Test with `/status all`

### Agent Customization

Agents inherit behavior from:
- `AGENTS.md`: Runtime context
- `.claude/rules/galaxy-orders.md`: Order processing protocol
- Custom agents in `.claude/agents/`: Specialized skills

### Outbox Notifications

Agents can send **unsolicited notifications** via outbox:

**In agent code**:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

outbox = Path(".sisyphus/notepads/galaxy-outbox")
outbox.mkdir(parents=True, exist_ok=True)

notification = {
    "type": "notification",
    "severity": "success",  # critical, warning, info, success, alert
    "from": "Build Agent",
    "message": "✅ Build completed successfully in 2m 34s",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "sent": False
}

(outbox / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json").write_text(
    json.dumps(notification, indent=2)
)
```

Bot polls outbox every 30s and sends to all authorized users.

---

## Related Documentation

- [Features Guide](features-guide.md) — Galaxy Protocol architecture comparison
- [Commands Guide](commands.md) — `/galaxy-standby` command reference
- `.claude/rules/galaxy-orders.md` — Agent-side order processing protocol
- `.sisyphus/JOURNAL.md` — "I Am Your Father" production test entry

---

## Changelog

| Date | Change | Phase |
|------|--------|-------|
| 2026-02-02 | Initial demo guide | Phase C hardening complete |
| 2026-02-02 | Security hardening deployed | Phase C |
| 2026-02-02 | MCP server production-ready | Phase C |
| 2026-02-02 | Phase 2.7 standby mode | Phase 2.7 |
| 2026-02-02 | Multi-machine architecture | Phase 2 |
| 2026-02-02 | Telegram bot v1 | Phase 3 |
