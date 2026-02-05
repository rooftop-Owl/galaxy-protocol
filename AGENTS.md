# Galaxy Protocol — astraeus Module

> **This is a variant module for [astraeus](https://github.com/rooftop-Owl/astraeus).**
> For the base system documentation, see the parent repository's AGENTS.md.

---

## Quick Start

```bash
# From your project (after astraeus is deployed):
astraeus load galaxy-protocol

# Configure Telegram bot and services
cp galaxy-protocol/tools/config.json.example .galaxy/config.json
# Edit .galaxy/config.json with your Telegram token and user ID

# Install dependencies
pip install -r galaxy-protocol/tools/requirements.txt

# Start services (from galaxy-protocol/galaxy-protocol/)
cd galaxy-protocol/galaxy-protocol
nohup python3 tools/caduceus/gateway.py --config ../.galaxy/config.json > /tmp/gateway.log 2>&1 &
nohup python3 tools/hermes.py --interval 5 > /tmp/hermes.log 2>&1 &
```

This loads **1 agent**, **3 commands**, **1 rule**, and the **Caduceus gateway** for multi-channel access.

---

## What This Module Provides

### 1 Specialized Agent

| Agent | Domain | Use For |
|-------|--------|---------|
| **star-curator** | GitHub management | Star list organization, sync, audit, auto-feed integration |

### 3 Commands

| Command | Purpose |
|---------|---------|
| `/galaxy-standby` | Enter polling loop to auto-process orders |
| `/stars` | Organize GitHub star lists + auto-feed repos into knowledge archive |
| `/feed` | Capture external references (repos, articles, papers) into `.sisyphus/references/` |

### 1 Rule

| Rule | Purpose |
|------|---------|
| `galaxy-orders` | Order detection, processing protocol, response format |

### Caduceus Gateway (Runtime)

Multi-channel message gateway supporting Telegram, Web, and future platforms.

| Component | Purpose |
|-----------|---------|
| `gateway.py` | Universal entry point — routes messages between channels and executors |
| `hermes.py` | Order dispatcher daemon — polls `.sisyphus/notepads/galaxy-orders/` |
| `feed_processor.py` | Knowledge capture — extracts content from URLs into references |
| `channels/telegram.py` | Telegram bot channel |
| `channels/web.py` | WebSocket-based web chat |
| `executors/hermes.py` | Filesystem bridge to Hermes daemon |

---

## Architecture

```
┌─ Channels (Wing 1) ──────────────────────────┐
│  Telegram  │  Web  │  (future: WhatsApp)      │
│  ↓         ↓       ↓                          │
└────────────┬──────────────────────────────────┘
             │
        ┌────▼─────┐
        │MessageBus│  ← async queues (inbound/outbound)
        └────┬─────┘
             │
┌────────────▼──────────────────────────────────┐
│  Hermes Executor  │  (future: Sandbox, Cluster)│
│  ↓                                             │
│  .sisyphus/notepads/galaxy-orders/            │
│  → Agent processes → Response                 │
└───────────────────────────────────────────────┘
```

**Message Flow**:
1. User sends via Telegram → `TelegramChannel` publishes to `MessageBus.inbound`
2. `HermesExecutor` consumes → writes order JSON to filesystem
3. `hermes.py` daemon polls → spawns agent via `opencode run`
4. Agent completes → writes response
5. `HermesExecutor` publishes to `MessageBus.outbound`
6. `TelegramChannel` consumes → sends reply to user

---

## Workflows

### 1. Remote Development Loop
```
Telegram message → Caduceus Gateway → MessageBus
  → Hermes Executor → order file
  → hermes.py polls → opencode run (persistent session)
  → Agent writes code → Response
  → MessageBus → Telegram
  → User tests locally → sends results
  → Agent fixes (same session, full context preserved)
```

### 2. GitHub Star Management + Auto-Feed
```
/stars https://github.com/owner/repo
  ↓
star-curator agent:
  1. Fetch repo metadata via gh CLI
  2. Auto-categorize into star lists
  3. Star the repo (gh api user/starred/...)
  4. Update tools/galaxy/stars.json
  5. Sync to GitHub via stars-sync.sh
  6. AUTO-FEED: call feed_processor.process_feed()
     → Ingest repo into .sisyphus/references/
  ↓
Output:
  ⭐ owner/repo → [List A, List B]
  📬 Fed into knowledge archive
```

### 3. Knowledge Capture (`/feed`)
```
/feed https://example.com "Optional note"
  ↓
feed_processor.py:
  1. Detect content type (GitHub, blog, paper, docs)
  2. Extract with trafilatura/newspaper4k
  3. Generate markdown:
     - Title, source, type, timestamp
     - Tags, note, via (telegram|tui)
     - Summary, key insights, relevance, patterns
  4. Save to .sisyphus/references/{slug}.md
  5. Update .sisyphus/references/index.json
  ↓
Indexed reference available for future context
```

**Integration**: `/stars` now auto-feeds repos after starring them, combining star organization with knowledge capture.

---

## Telegram Commands

| Command | Purpose |
|---------|---------|
| `/status [machine\|all]` | Machine status snapshot (git, tests, reports) |
| `/concerns [machine\|all]` | Latest Stargazer concerns |
| `/order [machine\|all] <msg>` | Send an order to a machine |
| `/feed <url> [note]` | Capture external reference into knowledge archive |
| `/machines` | List registered machines |
| `/help` | Show available commands |

---

## Knowledge Archive Structure

References stored in `.sisyphus/references/`:

```
.sisyphus/references/
├── index.json                           # Catalog: slug → metadata
├── 2026-02-04-trafilatura-extraction.md # GitHub repo
├── 2026-02-04-vercel-ai-sdk-3-0.md      # Blog post
└── 2026-02-04-in-context-learning.md    # Academic paper
```

**Reference Format**:
```markdown
# Title

**Source**: https://example.com
**Type**: repo|article|paper|post|docs|tool
**Ingested**: 2026-02-04T10:30:00Z
**Tags**: tag1, tag2, tag3
**Note**: Optional user note
**Via**: telegram|tui|stars

---

## Summary
## Key Insights
## Relevance to Our Work
## Applicable Patterns
```

**Discovery**:
- Quick lookup: Read `index.json`
- Deep search: Grep `*.md` files
- TUI: `/feed list [tag]`

---

## Configuration

`.galaxy/config.json`:

```json
{
  "telegram_token": "your-bot-token",
  "authorized_users": [123456789],
  "repo_path": "/home/user/astraeus",
  "machines": {
    "lab-server": {
      "default": true,
      "working_dir": "/home/user/project"
    }
  },
  "web": {
    "enabled": true,
    "port": 8080,
    "authorized_users": [123456789]
  }
}
```

---

## Module Management

```bash
astraeus load galaxy-protocol      # Load into project
astraeus status                    # Check module health
astraeus unload galaxy-protocol    # Clean removal (symlinks only)
```

---

## Production Deployment (systemd)

```bash
# Install services
sudo galaxy-protocol/tools/caduceus/install-service.sh

# Enable and start
sudo systemctl enable --now caduceus-gateway caduceus-hermes

# Check status
sudo systemctl status caduceus-gateway
sudo systemctl status caduceus-hermes

# View logs
journalctl -u caduceus-gateway -f
journalctl -u caduceus-hermes -f
```

---

## Design Philosophy

**Separation of Concerns**:
- **Channels**: Know platform APIs (Telegram, WebSocket)
- **MessageBus**: Routes messages asynchronously
- **Executors**: Process orders (filesystem bridge to hermes.py)
- **Gateway**: Orchestrates lifecycle, no business logic

**Filesystem Bridge**:
- Existing `.sisyphus/notepads/galaxy-orders/` protocol preserved
- Zero changes required to hermes.py or existing agents
- Async gateway wraps synchronous filesystem polling

**Async-First**:
- All I/O is async (`asyncio.Queue`, `async def`, `await`)
- Channels run concurrently via `asyncio.gather`
- No blocking operations on main event loop

---

## Files and Locations

```
galaxy-protocol/
├── .claude/
│   ├── agents/star-curator.md         # GitHub star management + auto-feed
│   ├── commands/
│   │   ├── galaxy-standby.md
│   │   ├── stars.md                   # /stars integration with /feed
│   │   └── feed.md                    # /feed knowledge capture
│   └── rules/galaxy-orders.md
├── tools/
│   ├── caduceus/
│   │   ├── gateway.py                 # Main entry point
│   │   ├── bus.py                     # MessageBus + dataclasses
│   │   ├── feed_processor.py          # Knowledge extraction
│   │   ├── channels/
│   │   │   ├── base.py
│   │   │   ├── telegram.py
│   │   │   └── web.py
│   │   ├── executors/
│   │   │   ├── base.py
│   │   │   └── hermes.py
│   │   ├── auth/
│   │   │   └── store.py               # User authentication
│   │   ├── static/
│   │   │   ├── index.html
│   │   │   └── app.js
│   │   └── README.md                  # Caduceus documentation
│   ├── hermes.py                      # Order dispatcher daemon
│   ├── galaxy/
│   │   ├── stars.json                 # Star list state
│   │   └── stars-sync.sh              # GitHub sync script
│   ├── config.json.example
│   └── requirements.txt
└── services/
    ├── caduceus-gateway.service
    └── caduceus-hermes.service
```

---

## See Also

- [MODULE_CONTEXT.md](MODULE_CONTEXT.md) — Module identity and purpose
- [module.json](module.json) — Module manifest
- [tools/caduceus/README.md](tools/caduceus/README.md) — Gateway architecture deep dive
- [tools/caduceus/ARCHITECTURE.md](tools/caduceus/ARCHITECTURE.md) — Design decisions
- [docs/galaxy-protocol-guide.md](docs/galaxy-protocol-guide.md) — Full user guide
- [docs/galaxy-production-deployment.md](docs/galaxy-production-deployment.md) — Production setup

---

## References

- **Caduceus**: Multi-channel gateway inspired by [nanobot](https://github.com/HKUDS/nanobot)
- **trafilatura**: Web content extraction ([adbar/trafilatura](https://github.com/adbar/trafilatura))
- **newspaper4k**: Article parsing ([newspaper4k](https://github.com/AndyTheFactory/newspaper4k))
- **python-telegram-bot**: Async Telegram bot framework
