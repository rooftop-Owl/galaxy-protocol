# Galaxy Protocol Production Deployment Guide

**Phase D1: Production Operations**

This guide covers deploying Galaxy Protocol to a production environment with monitoring, health checks, and operational tooling.

---

## Architecture Overview

```
┌─────────────────┐
│  Telegram Bot   │  Receives /order commands from phone
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Galaxy Orders  │  .sisyphus/notepads/galaxy-orders/*.json
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Galaxy MCP    │  Watches orders directory (FastMCP server)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ opencode serve  │  Persistent server on port 4096
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ opencode run    │  Fresh agent per order (--attach)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Agent System   │  Sisyphus + specialized agents
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Response      │  .sisyphus/notepads/galaxy-order-response-*.md
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Telegram      │  Bot sends response back to phone
└─────────────────┘
```

---

## ⚠️ Known Architectural Limitation (Phase D1)

**Current Implementation**: Galaxy Protocol uses **isolated agent sessions** per order.

### What This Means

Each order executes as:
```bash
opencode run --attach http://localhost:4096 "payload"
```

This creates a **fresh agent context** for every order, which means:

| Missing Capability | Impact |
|-------------------|--------|
| ❌ No Sisyphus orchestration | Orders are handled by basic agent, not routed to specialists |
| ❌ No delegation to specialized agents | Can't invoke Oracle, TDD Guide, Code Reviewer, etc. |
| ❌ No skill loading | Can't use git-master, frontend-ui-ux, or domain skills |
| ❌ No Code of Conduct enforcement | Missing quality gates and best practices |
| ❌ No session continuity | No memory between orders, no rolling context |
| ❌ No todo/boulder tracking | Can't coordinate multi-step workflows |

### What Works

| Working Capability | Status |
|-------------------|--------|
| ✅ Phone → Agent → Response | Basic request/reply works |
| ✅ Multi-machine routing | Orders routed to correct machine |
| ✅ Order queuing | Multiple orders handled sequentially |
| ✅ Monitoring & audit | Health checks, dashboard, logs all work |

### Why This Exists

**Design Decision (Phase C)**: "Fresh context per order" to avoid session compaction issues.

**Trade-off made**:
- ✅ Avoided compaction/memory issues
- ❌ Lost astraeus orchestration sophistication

### Planned Resolution

**Phase D2/E** will implement full Sisyphus integration:
- Orders processed within orchestrated session
- Full delegation to specialized agents
- Skill loading and Code of Conduct enforcement
- Rolling context window with session continuity
- Multi-step workflow support

See `.sisyphus/plans/galaxy-phase-d2-sisyphus-integration.md` for architecture design.

### Use Cases

**What Galaxy Protocol (Phase D1) is GOOD for**:
- Quick information retrieval
- Simple commands and queries
- Status checks and monitoring
- Exploratory questions

**What it's NOT GOOD for (yet)**:
- Complex multi-step workflows
- Code refactoring requiring architecture understanding
- Security-sensitive operations
- Operations requiring specialist agents (security review, TDD, etc.)

---

## Components

| Component | Purpose | Service |
|-----------|---------|---------|
| **opencode serve** | Persistent server for agent execution | `opencode-serve.service` |
| **Galaxy MCP** | Order watcher and executor | `galaxy-mcp.service` |
| **Telegram Bot** | User interface via phone | `galaxy.service` |
| **Health Check** | Monitors system health | `galaxy-health-check.timer` |
| **Dashboard** | Web monitoring UI (port 5000) | `galaxy-dashboard.service` |
| **Audit Log** | Compliance and debugging | `logs/galaxy-audit.jsonl` |

---

## Prerequisites

### System Requirements
- Ubuntu 20.04+ or similar Linux distribution
- Python 3.9+
- systemd (for service management)
- 4GB+ RAM recommended
- 10GB+ disk space

### Software Dependencies
```bash
sudo apt update
sudo apt install -y python3 python3-pip curl systemd
```

### Python Dependencies
```bash
cd /path/to/galaxy-protocol
pip3 install -r tools/galaxy/requirements.txt
```

---

## Installation

### 1. Clone Repository
```bash
git clone https://github.com/your-org/galaxy-protocol.git
cd galaxy-protocol
```

### 2. Configure Galaxy
```bash
mkdir -p .galaxy
cp tools/galaxy/config.json.example .galaxy/config.json
```

Edit `.galaxy/config.json`:
```json
{
  "telegram_token": "YOUR_BOT_TOKEN",
  "authorized_users": [123456789],
  "default_machine": "production",
  "machines": {
    "production": {
      "host": "localhost",
      "repo_path": "/path/to/galaxy-protocol",
      "machine_name": "production"
    }
  }
}
```

### 3. Create Directories
```bash
mkdir -p .sisyphus/notepads/galaxy-orders
mkdir -p .sisyphus/notepads/galaxy-orders-archive
mkdir -p .sisyphus/notepads/galaxy-outbox
mkdir -p logs
```

### 4. Install Systemd Services

**Update service files** with correct paths:
```bash
# Edit WorkingDirectory in each service file
sed -i "s|/home/zephyr/projects/galaxy-protocol|$(pwd)|g" \
  tools/galaxy/*.service \
  tools/galaxy/galaxy-health-check.service \
  tools/galaxy/galaxy-health-check.timer
```

**Install for user systemd:**
```bash
mkdir -p ~/.config/systemd/user
cp tools/galaxy/opencode-serve.service ~/.config/systemd/user/
cp tools/galaxy/galaxy-mcp.service ~/.config/systemd/user/
cp tools/galaxy/galaxy.service ~/.config/systemd/user/
cp tools/galaxy/galaxy-health-check.service ~/.config/systemd/user/
cp tools/galaxy/galaxy-health-check.timer ~/.config/systemd/user/
cp tools/galaxy/galaxy-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

**Install for system-wide (requires sudo):**
```bash
sudo cp tools/galaxy/*.service /etc/systemd/system/
sudo cp tools/galaxy/galaxy-health-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5. Enable and Start Services

**User systemd:**
```bash
systemctl --user enable --now opencode-serve.service
systemctl --user enable --now galaxy-mcp.service
systemctl --user enable --now galaxy.service
systemctl --user enable --now galaxy-health-check.timer
systemctl --user enable --now galaxy-dashboard.service
```

**System-wide:**
```bash
sudo systemctl enable --now opencode-serve.service
sudo systemctl enable --now galaxy-mcp.service
sudo systemctl enable --now galaxy.service
sudo systemctl enable --now galaxy-health-check.timer
sudo systemctl enable --now galaxy-dashboard.service
```

---

## Verification

### Check Service Status
```bash
systemctl --user status opencode-serve.service
systemctl --user status galaxy-mcp.service
systemctl --user status galaxy.service
systemctl --user status galaxy-health-check.timer
systemctl --user status galaxy-dashboard.service
```

All services should show `Active: active (running)`.

### Check Health
```bash
./tools/galaxy/health-check.sh
```

Expected output:
```
[2026-02-02T12:00:00Z] === Galaxy Protocol Health Check ===
[2026-02-02T12:00:00Z] ✓ opencode serve is healthy
[2026-02-02T12:00:00Z] ✓ Galaxy MCP is running
[2026-02-02T12:00:00Z] ✓ Disk space OK (26% used)
[2026-02-02T12:00:00Z] === Health Check PASSED ===
```

### Access Monitoring Dashboard
```bash
curl http://localhost:5000/api/status
```

Or open in browser: `http://your-server-ip:5000`

### Test Order Execution
Create a test order:
```bash
cat > .sisyphus/notepads/galaxy-orders/test-$(date +%Y%m%d-%H%M%S).json <<EOF
{
  "type": "galaxy_order",
  "from": "test",
  "target": "production",
  "command": "general",
  "payload": "Test: Echo hello world",
  "timestamp": "$(date -Iseconds)",
  "acknowledged": false
}
EOF
```

Wait 5-10 seconds and check:
```bash
ls -la .sisyphus/notepads/galaxy-orders-archive/
ls -la .sisyphus/notepads/galaxy-order-response-*.md | tail -1
```

---

## Monitoring

### View Logs
```bash
# Service logs
journalctl --user -u opencode-serve.service -f
journalctl --user -u galaxy-mcp.service -f
journalctl --user -u galaxy.service -f

# Health check logs
tail -f logs/galaxy-health.log

# Audit trail
python3 tools/galaxy/audit.py --limit 20
```

### Metrics Dashboard
Open `http://your-server-ip:5000` in browser for real-time metrics:
- System uptime
- Pending/processed/failed order counts
- OpenCode server health
- Galaxy MCP status
- Disk usage
- Recent health check logs

### Audit Queries
```bash
# Show all events
python3 tools/galaxy/audit.py --limit 100

# Show only errors
python3 tools/galaxy/audit.py --severity error

# Show order executions
python3 tools/galaxy/audit.py --type order_executed_success

# JSON output
python3 tools/galaxy/audit.py --json --limit 50
```

---

## Troubleshooting

### Service won't start
```bash
# Check logs for errors
journalctl --user -u service-name.service -n 50

# Common issues:
# 1. Port already in use
sudo lsof -i :4096
sudo lsof -i :5000

# 2. Permission denied
chmod +x tools/galaxy/*.sh
chmod +x tools/galaxy/*.py

# 3. Missing dependencies
pip3 install -r tools/galaxy/requirements.txt
```

### Orders not processing
```bash
# Check Galaxy MCP is running
pgrep -f galaxy_mcp.py

# Check opencode serve is reachable
curl -I http://localhost:4096/health

# Check for stale locks
ls -la .sisyphus/notepads/galaxy-orders/*.processing

# Restart MCP
systemctl --user restart galaxy-mcp.service
```

### Health checks failing
```bash
# Run health check manually
./tools/galaxy/health-check.sh

# Check disk space
df -h

# Check service health
systemctl --user status opencode-serve.service
systemctl --user status galaxy-mcp.service
```

---

## Maintenance

### Cleanup Old Files
```bash
# Archive old response files (30+ days)
find .sisyphus/notepads -name "galaxy-order-response-*.md" -mtime +30 -delete

# Archive old logs
find logs -name "*.log" -mtime +90 -exec gzip {} \;

# Archive old audit logs
find logs -name "galaxy-audit.jsonl" -mtime +180 -exec gzip {} \;
```

### Backup
```bash
# Backup configuration
tar -czf galaxy-config-$(date +%Y%m%d).tar.gz \
  .galaxy/config.json \
  .mcp.json

# Backup audit logs
tar -czf galaxy-audit-$(date +%Y%m%d).tar.gz \
  logs/galaxy-audit.jsonl \
  logs/galaxy-health.log
```

### Updates
```bash
# Pull latest code
git pull origin main

# Restart services
systemctl --user restart galaxy-mcp.service
systemctl --user restart galaxy.service
systemctl --user restart galaxy-dashboard.service
```

---

## Security

### Telegram Bot Token
- **Never commit** `.galaxy/config.json` to git
- Store token in environment variable:
  ```bash
  export GALAXY_TELEGRAM_TOKEN="your-token"
  ```
- Use `.gitignore`:
  ```
  .galaxy/config.json
  ```

### Authorized Users
- Only add trusted user IDs to `authorized_users` list
- Get user ID by sending `/start` to your bot

### Firewall
```bash
# Only expose dashboard on localhost
# Edit galaxy-dashboard.service: --host 127.0.0.1

# Use SSH tunnel for remote access
ssh -L 5000:localhost:5000 user@your-server
```

---

## Performance Tuning

### Increase Worker Processes
For high order volume, run multiple Galaxy MCP instances:
```bash
# galaxy-mcp@1.service, galaxy-mcp@2.service, etc.
systemctl --user enable --now galaxy-mcp@{1..3}.service
```

### Optimize opencode serve
```bash
# Increase memory limit if needed
export NODE_OPTIONS="--max-old-space-size=4096"
```

### Monitor Resource Usage
```bash
# CPU/Memory per service
systemd-cgtop

# Disk I/O
iotop -o

# Network
nethogs
```

---

## Phase D1 Success Criteria

- [x] All services running 24/7
- [x] Health check timer running every 5 minutes
- [x] Dashboard accessible on port 5000
- [x] Audit log capturing all events
- [x] Orders processed successfully
- [x] Alerts sent to outbox on failures
- [ ] < 1 minute failure detection
- [ ] < 5 minute recovery from failures
- [ ] 100% order audit trail

---

## Next Steps (Phase D2+)

After Phase D1 is stable, consider:

1. **Enhanced UX** (Phase D2)
   - Inline keyboards in Telegram
   - Progress indicators for long orders
   - Rich responses (images, files)

2. **Scale & Performance** (Phase D3)
   - Queue management for high volume
   - Worker pools for concurrent execution
   - Rate limiting and backpressure

3. **Advanced Features** (Phase D4)
   - Scheduled orders
   - Persistent workflows
   - File attachments
   - Group chat support

---

## Support

- **Documentation**: [docs/guides/](../guides/)
- **Issues**: GitHub Issues
- **Logs**: `logs/galaxy-*.log`
- **Audit**: `python3 tools/galaxy/audit.py`

---

**Galaxy Protocol Production Deployment v1.0 | Phase D1**
