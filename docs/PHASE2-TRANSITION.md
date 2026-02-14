# Phase 2 Transition Plan

> Note: This document is for Caduceus infrastructure transition only.
> Multimodal ingestion features are tracked separately in
> `prop-2026-02-13-galaxy-protocol-phase3-revised`.

## Current State: Phase 1 (Local Submodule Testing)

Caduceus Gateway is **production-verified** in Phase 1 configuration:
- All services run from submodule directory (`galaxy-protocol/`)
- Paths use `MODULE_ROOT` (submodule root) for testing isolation
- Web auth bypasses dynamic `web-*` IDs for localhost access
- 34 unit tests passing, live stress tests passed

**Live testing results**:
- ✅ Telegram → Gateway → Hermes → Agent → response (sub-5s)
- ✅ Web UI on localhost + mobile (192.168.68.56:8080)
- ✅ Concurrent messages, FIFO preserved
- ✅ No memory leaks, resource cleanup verified

---

## Phase 2: Production from Parent Repository

### Goal
Run Caduceus Gateway and Hermes from **parent repository** (`~/projects/galaxy-protocol/`) with full astraeus orchestration context.

### Path Changes Required

#### 1. `tools/hermes.py` (lines 24-34)

**Current (Phase 1)**:
```python
# PHASE 1: Testing locally in submodule (use MODULE_ROOT for all paths)
REPO_ROOT = Path(__file__).parent.parent.parent  # project root
MODULE_ROOT = Path(__file__).parent.parent  # galaxy-protocol module root
ORDERS_DIR = MODULE_ROOT / ".sisyphus/notepads/galaxy-orders"
ARCHIVE_DIR = MODULE_ROOT / ".sisyphus/notepads/galaxy-orders-archive"
RESPONSE_DIR = MODULE_ROOT / ".sisyphus/notepads"
OUTBOX_DIR = MODULE_ROOT / ".sisyphus/notepads/galaxy-outbox"
HEARTBEAT_FILE = MODULE_ROOT / ".sisyphus/notepads/galaxy-session-heartbeat.json"
GALAXY_CONFIG = REPO_ROOT / ".galaxy/config.json"  # Config stays in parent
SESSION_FILE = MODULE_ROOT / ".galaxy/hermes-session.json"
```

**Phase 2 (Production)**:
```python
# PHASE 2: Production (running from parent repo with full astraeus context)
REPO_ROOT = Path(__file__).parent.parent.parent  # project root
MODULE_ROOT = Path(__file__).parent.parent  # galaxy-protocol module root
ORDERS_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders"  # ← Changed
ARCHIVE_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders-archive"  # ← Changed
RESPONSE_DIR = REPO_ROOT / ".sisyphus/notepads"  # ← Changed
OUTBOX_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-outbox"  # ← Changed
HEARTBEAT_FILE = REPO_ROOT / ".sisyphus/notepads/galaxy-session-heartbeat.json"  # ← Changed
GALAXY_CONFIG = REPO_ROOT / ".galaxy/config.json"
SESSION_FILE = REPO_ROOT / ".galaxy/hermes-session.json"  # ← Changed
```

**Rationale**: Hermes should watch parent repo's `.sisyphus/notepads/` where astraeus agents write orders.

---

#### 2. `tools/caduceus/gateway.py` (lines 142-151)

**Current (Phase 1)**:
```python
# PHASE 1: Testing locally in submodule (use current working directory)
repo_root = Path.cwd()  # Current directory for Phase 1 testing
executor_config = {
    "orders_dir": str(repo_root / ".sisyphus" / "notepads" / "galaxy-orders"),
    "timeout": config.get("executor_timeout", 180),
    "poll_interval": config.get("executor_poll_interval", 1.0),
}
```

**Phase 2 (Production)**:
```python
# PHASE 2: Production (use config.get("repo_path") from .galaxy/config.json)
repo_root = Path(config.get("repo_path", Path.cwd()))
executor_config = {
    "orders_dir": str(repo_root / ".sisyphus" / "notepads" / "galaxy-orders"),
    "timeout": config.get("executor_timeout", 180),
    "poll_interval": config.get("executor_poll_interval", 1.0),
}
```

**Rationale**: Gateway reads `repo_path` from config to know where parent repo is located.

---

#### 3. `tools/caduceus/channels/web.py` (lines 92-95)

**Current (Phase 1)**:
```python
# Authorization check (skip for dynamically generated web-* IDs on localhost)
if self.authorized_users and not sender_id.startswith("web-"):
    if sender_id not in self.authorized_users:
        await ws.send_json({"type": "error", "content": "Unauthorized"})
```

**Phase 2 (Production)** - Two options:

**Option A: Keep bypass for convenience** (recommended for personal use):
```python
# Skip auth for dynamically generated web-* IDs (localhost only)
if self.authorized_users and not sender_id.startswith("web-"):
    if sender_id not in self.authorized_users:
        await ws.send_json({"type": "error", "content": "Unauthorized"})
```

**Option B: Proper authentication** (for multi-user deployment):
```python
# Implement login page → JWT token → persistent user_id mapping
# Replace web-{id(ws)} with authenticated user_id from session
# See: docs/authentication-design.md (to be created)
```

---

### Configuration Update

Update `.galaxy/config.json` with correct `repo_path`:

**Current**:
```json
{
  "machines": {
    "zephyr": {
      "host": "localhost",
      "repo_path": "/home/zephyr/astraeus",  // ← Wrong path
      "machine_name": "zephyr"
    }
  }
}
```

**Phase 2**:
```json
{
  "machines": {
    "zephyr": {
      "host": "localhost",
      "repo_path": "/home/zephyr/projects/galaxy-protocol",  // ← Parent repo
      "machine_name": "zephyr"
    }
  }
}
```

---

### Execution Changes

**Phase 1 (Current)**:
```bash
cd ~/projects/galaxy-protocol/galaxy-protocol  # Submodule
python3 tools/hermes.py --interval 5
python3 tools/caduceus/gateway.py --config ../.galaxy/config.json
```

**Phase 2 (Production)**:
```bash
cd ~/projects/galaxy-protocol  # Parent repo
python3 galaxy-protocol/tools/hermes.py --interval 5
python3 galaxy-protocol/tools/caduceus/gateway.py --config .galaxy/config.json
```

---

## Migration Steps

### When Ready to Transition

1. **Stop Phase 1 services**:
   ```bash
   # Kill Hermes and Gateway processes
   pkill -f "hermes.py"
   pkill -f "gateway.py"
   ```

2. **Apply code changes**:
   - Edit `tools/hermes.py` lines 24-34 (change MODULE_ROOT → REPO_ROOT)
   - Edit `tools/caduceus/gateway.py` lines 142-151 (use `config.get("repo_path")`)
   - Optionally update `tools/caduceus/channels/web.py` for production auth

3. **Update config**:
   - Edit `.galaxy/config.json` with correct `repo_path`

4. **Commit changes**:
   ```bash
   cd ~/projects/galaxy-protocol/galaxy-protocol
   git add tools/hermes.py tools/caduceus/gateway.py
   git commit -m "feat: Phase 2 production paths for parent repo execution"
   ```

5. **Start Phase 2 services**:
   ```bash
   cd ~/projects/galaxy-protocol  # Parent repo
   python3 galaxy-protocol/tools/hermes.py --interval 5 &
   python3 galaxy-protocol/tools/caduceus/gateway.py --config .galaxy/config.json
   ```

6. **Verify**:
   - Send test message via Telegram
   - Check order appears in parent's `.sisyphus/notepads/galaxy-orders/`
   - Verify response delivered successfully
   - Test web UI access

---

## Rollback Plan

If Phase 2 fails:

1. **Stop Phase 2 services** (same as step 1 above)
2. **Revert code changes**:
   ```bash
   cd ~/projects/galaxy-protocol/galaxy-protocol
   git revert HEAD  # Undo Phase 2 commit
   ```
3. **Restart Phase 1 services** (same as current setup)

---

## Testing Checklist

Before declaring Phase 2 complete:

- [ ] Telegram messages delivered successfully
- [ ] Web UI accessible and responsive
- [ ] Orders written to parent `.sisyphus/notepads/galaxy-orders/`
- [ ] Responses written to parent `.sisyphus/notepads/`
- [ ] Concurrent messages handled correctly
- [ ] Resource cleanup (order files archived, response files deleted)
- [ ] No memory leaks after 10+ messages
- [ ] Heartbeat updates in parent `.sisyphus/notepads/galaxy-session-heartbeat.json`
- [ ] Session continuity across service restarts

---

## Future Enhancements (Post-Phase 2)

### Authentication System
- Login page with username/password
- JWT token generation
- Persistent `user_id` mapping for web sessions
- Replace `web-{id(ws)}` with authenticated `user_id`

### Multi-Machine Support
- Gateway routes to different machines based on config
- Load balancing across multiple astraeus instances
- Failover if primary machine is offline

### Monitoring Dashboard
- Real-time order queue visualization
- Response time metrics
- Agent session status
- Error rate tracking

### Advanced Features
- Message history pagination in web UI
- File upload support (images, documents)
- Voice message transcription
- Multi-user chat rooms

---

## Questions?

See:
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [MIGRATION.md](MIGRATION.md) - Migration from bot.py
- [README.md](README.md) - Usage and examples
- [docs/guides/galaxy-protocol-guide.md](../../docs/guides/galaxy-protocol-guide.md) - Full guide

Or ask in astraeus session:
```
opencode
> How do I transition Caduceus Gateway to Phase 2?
```
