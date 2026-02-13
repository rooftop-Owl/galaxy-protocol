# Galaxy Protocol — astraeus Module

> **This is a variant module for [astraeus](https://github.com/rooftop-Owl/astraeus).**
> For the base system documentation, see the parent repository's AGENTS.md.

## Purpose

Galaxy Protocol enables **remote control** of astraeus from anywhere — phone, tablet, laptop, web.
Send orders via Telegram, receive agent responses. Persistent sessions maintain conversation
continuity across messages.

## Architecture

```
Phone → Telegram → bot.py (any text = order)
                     ↓
              order JSON → .sisyphus/notepads/galaxy-orders/
                     ↓
              Hermes (polls every 5s)
                     ↓
              opencode run --session <persistent> "<prompt>"
                     ↓
              Agent executes (3 min timeout)
                     ↓
              response → outbox → bot.py → Telegram
```

## Components

| Component | File | Purpose |
|-----------|------|---------|
| **Telegram Bot** | `tools/bot.py` | Receives orders, delivers responses |
| **Hermes** | `tools/hermes.py` | Polls for orders, dispatches to agents |
| **Feature Handlers** | `tools/handlers/*.py` | DeepWiki, voice, OCR/PDF, routing, digest push |
| **Galaxy MCP** | `tools/galaxy_mcp.py` | MCP server for order processing |
| **Dashboard** | `tools/dashboard.py` | Web monitoring dashboard |
| **Star Curator** | `.claude/agents/star-curator.md` | GitHub star list management |

## Key Features

- **Zero idle cost** — No LLM calls when no orders pending
- **Persistent sessions** — Agent remembers previous messages
- **Silent operation** — Only notifies on errors, not on startup/shutdown
- **Territory sandbox** — Agent writes only to designated workspace
- **Concise mode** — Responses optimized for Telegram chat

## Runtime State

Galaxy Protocol creates these directories at runtime (not part of module):
- `.sisyphus/notepads/galaxy-orders/` — Incoming orders
- `.sisyphus/notepads/galaxy-orders-archive/` — Processed orders
- `.sisyphus/notepads/galaxy-outbox/` — Pending Telegram deliveries
- `.galaxy/config.json` — Bot configuration (gitignored)
- `.galaxy/hermes-session.json` — Persistent session ID
