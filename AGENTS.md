# Galaxy Protocol — astraeus Module

> **This is a variant module for [astraeus](https://github.com/rooftop-Owl/astraeus).**
> For the base system documentation, see the parent repository's AGENTS.md.

---

## Quick Start

```bash
# From your project (after astraeus is deployed):
astraeus load galaxy-protocol

# Configure Telegram bot
cp galaxy-protocol/tools/config.json.example .galaxy/config.json
# Edit .galaxy/config.json with your Telegram token and user ID

# Install dependencies
pip install -r galaxy-protocol/tools/requirements.txt

# Start services
python3 galaxy-protocol/tools/bot.py &
python3 galaxy-protocol/tools/hermes.py --interval 5 &
```

This loads 1 agent, 2 commands, 1 rule, and 3 runtime tools.

---

## What This Module Provides

### 1 Specialized Agent

| Agent | Domain | Use For |
|-------|--------|---------|
| **star-curator** | GitHub management | Star list organization, sync, audit |

### 2 Commands

| Command | Purpose |
|---------|---------|
| `/galaxy-standby` | Enter polling loop to auto-process orders |
| `/stars` | Organize GitHub star lists |

### 1 Rule

| Rule | Purpose |
|------|---------|
| `galaxy-orders` | Order detection, processing protocol, response format |

### 3 Runtime Tools

| Tool | Purpose |
|------|---------|
| `bot.py` | Telegram bot — bidirectional relay |
| `hermes.py` | Order dispatcher daemon — polls and delivers |
| `galaxy_mcp.py` | MCP server for programmatic order processing |

---

## Workflows

### Remote Development Loop
```
Telegram message → bot.py → order file
  → Hermes dispatches → Agent writes code
  → Response → Telegram
  → User tests locally → sends results
  → Agent fixes (same session, full context)
```

### GitHub Star Management
```
/stars → star-curator agent → stars-sync.sh → organized star lists
```

---

## Module Management

```bash
astraeus load galaxy-protocol      # Load into project
astraeus status                    # Check health
astraeus unload galaxy-protocol    # Clean removal
```

See also:
- [MODULE_CONTEXT.md](MODULE_CONTEXT.md) — Identity doc
- [module.json](module.json) — Manifest
- [docs/galaxy-protocol-guide.md](docs/galaxy-protocol-guide.md) — Full guide
- [docs/galaxy-production-deployment.md](docs/galaxy-production-deployment.md) — Production setup
