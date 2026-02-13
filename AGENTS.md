# Galaxy Protocol - astraeus Module

> Remote orchestration module for Telegram/Web entry points, order dispatch, and knowledge capture.

## Quick Start

```bash
astraeus load galaxy-protocol
cp galaxy-protocol/tools/config.json.example .galaxy/config.json
pip install -r galaxy-protocol/tools/requirements.txt
```

## What This Module Provides

- **Agent**: `star-curator`
- **Commands**: `/galaxy-standby`, `/stars`, `/feed`
- **Rule**: `galaxy-orders`
- **Runtime components**: `tools/caduceus/gateway.py`, `tools/hermes.py`, `tools/feed_processor.py`, `tools/handlers/*.py`

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Module architecture | `docs/galaxy-protocol-guide.md` | Full operational docs |
| Runtime services | `services/` + `tools/caduceus/` | Gateway, channels, executors |
| Telegram integration | `tools/caduceus/channels/telegram.py` | Bot channel adapter |
| Order processing | `tools/hermes.py` | Polling and execution loop |
| Feed capture | `tools/feed_processor.py` | URL extraction and indexing |
| Config | `.galaxy/config.json` | Token, user, machine mapping |

## Core Flows
```
Remote Loop: Channel -> MessageBus -> Hermes executor -> opencode run -> response
Star Loop: /stars -> classify/sync -> optional auto-feed to references
Feed Loop: /feed URL -> extract -> markdown reference -> index update
```

## Module Management
```bash
astraeus load galaxy-protocol
astraeus status
astraeus unload galaxy-protocol
```

## CONVENTIONS
- Keep runtime queue/order state in module-local `.sisyphus/` buffers.
- Keep committed synthesis artifacts in root `.sisyphus/` (`digests/`, `stars.json`).
- Keep command behavior consistent between TUI and Telegram interfaces.

## ANTI-PATTERNS
- NEVER commit `tools/config.json` (contains secrets).
- NEVER create or execute Galaxy orders without explicit user intent.
- NEVER change order schema without updating gateway + bot + MCP integration.
