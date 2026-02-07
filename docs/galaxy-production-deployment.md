# Galaxy Protocol Production Deployment Guide

**Phase 2: Caduceus + Hermes Architecture**

This guide covers deploying Galaxy Protocol with the current Phase 2 architecture: Caduceus gateway (Telegram) + Hermes executor (order dispatcher).

> **Note**: This document covers the modern Phase 2 architecture. For legacy Phase D1 (galaxy-mcp), see the archive section.

---

## Phase 2 Architecture Overview

```
┌──────────────────┐
│  Telegram App    │  User sends commands from phone
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Caduceus        │  Multi-channel gateway (Telegram polling)
│  Gateway         │  tools/caduceus/gateway.py
└────────┬─────────┘
         │ writes
         ▼
┌──────────────────┐
│  Galaxy Orders   │  .sisyphus/notepads/galaxy-orders/*.json
└────────┬─────────┘
         │ polls (30s interval)
         ▼
┌──────────────────┐
│  Hermes          │  Order dispatcher daemon
│  Executor        │  tools/hermes.py
└────────┬─────────┘
         │ spawns
         ▼
┌──────────────────┐
│ opencode run     │  Full agent session with persistent context
│ (persistent)     │  Session continuity via hermes-session.json
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Agent System    │  Sisyphus orchestration + specialized agents
│  (Sisyphus)      │  Full delegation, skills, Code of Conduct
└────────┬─────────┘
         │ writes
         ▼
┌──────────────────┐
│   Response       │  .sisyphus/notepads/galaxy-order-response-*.md
└────────┬─────────┘
         │ reads
         ▼
┌──────────────────┐
│  Caduceus        │  Sends response back via Telegram
│  Gateway         │
└──────────────────┘
```

**Key Differences from Phase D1**:
- ✅ **Persistent sessions**: Hermes maintains session continuity across orders
- ✅ **Full Sisyphus orchestration**: Orders processed with full agent system
- ✅ **Multi-channel**: Caduceus supports Telegram, Web, and future channels
- ✅ **Async architecture**: Gateway and executor run independently

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

| Component | Purpose | Service | Status |
|-----------|---------|---------|--------|
| **Caduceus Gateway** | Multi-channel message gateway (Telegram polling) | `caduceus-gateway.service` | Required |
| **Hermes Executor** | Order dispatcher daemon (30s polling) | `caduceus-hermes.service` | Required |
| **opencode** | Agent runtime (spawned by Hermes, no daemon) | N/A | Automatic |

---

## Prerequisites

### System Requirements
- Ubuntu 20.04+ or similar Linux distribution
- **Python 3.7+** (required for subprocess.capture_output in Hermes)
- systemd (for service management)
- opencode CLI installed (`~/.opencode/bin/opencode`)
- 4GB+ RAM recommended
- 10GB+ disk space

### Software Dependencies
```bash
sudo apt update
sudo apt install -y python3 python3-pip curl systemd git
```

### Python Dependencies
```bash
cd /path/to/astraeus/galaxy-protocol
pip3 install -r tools/requirements.txt
```

### Critical Requirements

**Python Version**: Hermes uses `subprocess.run(capture_output=True)` which requires Python 3.7+. System Python (`/usr/bin/python3`) on older distributions may be 3.6.x and will fail with:
```
TypeError: __init__() got an unexpected keyword argument 'capture_output'
```

**Solution**: Use Anaconda or pyenv Python 3.7+:
```bash
# Check Python version
python3 --version  # Must be 3.7+

# If using Anaconda
which python3      # Should point to ~/anaconda3/bin/python3
```

**PATH Requirements**: Hermes spawns `opencode run` which requires `opencode` binary in PATH. The systemd service must include:
```ini
Environment="PATH=/home/user/.opencode/bin:/home/user/anaconda3/bin:/usr/local/bin:/usr/bin:/bin"
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

### 4. Configure Systemd Services

**Template service files** are in `galaxy-protocol/services/`:
- `caduceus-gateway.service` — Telegram polling daemon
- `caduceus-hermes.service` — Order dispatcher daemon

**Install services** (replace `/home/doyoon` with your home directory and `/home/doyoon/anaconda3` with your Python 3.7+ path):

```bash
# Create user systemd directory
mkdir -p ~/.config/systemd/user

# Copy service templates
cp galaxy-protocol/services/caduceus-gateway.service ~/.config/systemd/user/
cp galaxy-protocol/services/caduceus-hermes.service ~/.config/systemd/user/

# Edit service files with your paths
# Replace /home/doyoon with YOUR home directory
# Replace /home/doyoon/anaconda3 with YOUR Python 3.7+ installation
nano ~/.config/systemd/user/caduceus-gateway.service
nano ~/.config/systemd/user/caduceus-hermes.service

# Reload systemd
systemctl --user daemon-reload
```

**Key service file edits**:

For `caduceus-gateway.service`:
```ini
[Service]
WorkingDirectory=/home/YOUR_USER/astraeus  # ← Change this
ExecStart=/home/YOUR_USER/anaconda3/bin/python3 /home/YOUR_USER/astraeus/galaxy-protocol/tools/caduceus/gateway.py --config /home/YOUR_USER/astraeus/.galaxy/config.json  # ← Change all paths
```

For `caduceus-hermes.service`:
```ini
[Service]
WorkingDirectory=/home/YOUR_USER/astraeus  # ← Change this
ExecStart=/home/YOUR_USER/anaconda3/bin/python3 /home/YOUR_USER/astraeus/galaxy-protocol/tools/hermes.py --interval 30  # ← Change Python path
Environment="PATH=/home/YOUR_USER/.opencode/bin:/home/YOUR_USER/anaconda3/bin:/usr/local/bin:/usr/bin:/bin"  # ← Change paths
```

### 5. Enable and Start Services

```bash
# Enable services to start on boot
systemctl --user enable caduceus-gateway
systemctl --user enable caduceus-hermes

# Start services now
systemctl --user start caduceus-gateway
systemctl --user start caduceus-hermes
```

**Verify services are running**:
```bash
systemctl --user status caduceus-gateway --no-pager
systemctl --user status caduceus-hermes --no-pager
```

Expected output:
```
● caduceus-gateway.service - Caduceus Gateway - Telegram Bot
   Active: active (running) since ...
   
● caduceus-hermes.service - Caduceus Hermes - Galaxy Order Dispatcher  
   Active: active (running) since ...
```

---

## Verification

### Check Service Status
```bash
systemctl --user status caduceus-gateway
systemctl --user status caduceus-hermes
```

Both services should show `Active: active (running)`.

### Check Process Status
```bash
# Verify Caduceus gateway is running
ps aux | grep "caduceus/gateway.py" | grep -v grep

# Verify Hermes is running  
ps aux | grep "hermes.py" | grep -v grep
```

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
