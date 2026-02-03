# Caduceus — The Gateway That Gives Hermes Wings

> Multi-channel gateway for Galaxy Protocol, transforming it from a Telegram-specific bot into a universal access layer.

## What It Does

**Before Caduceus**: Galaxy Protocol = Telegram bot → one channel, tightly coupled  
**After Caduceus**: Galaxy Protocol = universal gateway → any channel (Telegram, Web, future: WhatsApp, CLI, API)

Caduceus gives Hermes (the order dispatcher) two wings:
- **Wing 1 (Channels)**: Hear from any world — Telegram, web, API, cron
- **Wing 2 (Executors)**: Act in any world — Hermes daemon, sandboxes, clusters

## Architecture

```
┌─ Wing 1: Channels ──────────────────────────┐
│  Telegram │ Web │ WhatsApp │ CLI │ API      │
│  (BaseChannel implementations)               │
└────────────────┬────────────────────────────┘
                 │
            ┌────▼─────┐
            │MessageBus│  ← The rod (asyncio.Queue)
            └────┬─────┘
                 │
┌────────────────▼────────────────────────────┐
│  Hermes │ Sandbox │ Local │ Cluster         │
│  (Executor implementations)                  │
└─ Wing 2: Executors ────────────────────────┘
```

**Message Flow**:
1. User sends message → Channel receives
2. Channel creates `InboundMessage` → publishes to MessageBus
3. Executor consumes from bus → processes order
4. Executor creates `OutboundMessage` → publishes to MessageBus  
5. Channel consumes from bus → sends response to user

## Components

### BaseChannel (Abstract)

Platform-agnostic channel interface. All chat platforms implement this.

**Interface**:
```python
class BaseChannel(ABC):
    async def start()  # Initialize and begin listening
    async def stop()   # Graceful shutdown
    async def send(msg: OutboundMessage)  # Send to user
    async def _handle_message(...)  # Publish InboundMessage to bus
```

**Implementations**:
- `TelegramChannel` — Telegram bot (extracted from original bot.py)
- `WebChannel` — WebSocket-based web chat
- Future: `WhatsAppChannel`, `CLIChannel`, `APIChannel`

### MessageBus

Async queue-based message router using `asyncio.Queue`.

**Queues**:
- `inbound`: Channels → Executor (user messages)
- `outbound`: Executor → Channels (agent responses)

**Messages**:
- `InboundMessage`: channel, sender_id, chat_id, content, media, metadata
- `OutboundMessage`: channel, chat_id, content

**Session Management**:
- `InboundMessage.session_key` = `f"{channel}:{chat_id}"` for continuity

### Executor (Abstract)

Execution backend interface. All order processors implement this.

**Interface**:
```python
class Executor(ABC):
    async def execute(order: dict) -> dict
```

**Implementations**:
- `HermesExecutor` — Wraps existing hermes.py daemon via filesystem bridge
- Future: `MicrosandboxExecutor`, `LocalExecutor`, `ClusterExecutor`

### Gateway

Orchestrates channels + executors with lifecycle management.

**Responsibilities**:
- Load config → instantiate channels + executor
- Start all components via `asyncio.gather`
- Route inbound messages to executor
- Route outbound messages to channels
- Graceful shutdown on SIGINT/SIGTERM

## Usage

### Development

```bash
# Start gateway (replace bot.py)
python3 galaxy-protocol/tools/caduceus/gateway.py --config .galaxy/config.json

# Test mode (dry-run)
python3 galaxy-protocol/tools/caduceus/gateway.py --test-mode

# With logging
python3 galaxy-protocol/tools/caduceus/gateway.py --log-level DEBUG
```

### Production (systemd)

```bash
# Install service
sudo galaxy-protocol/tools/caduceus/install-service.sh

# Enable and start
sudo systemctl enable --now caduceus-gateway

# Check status
sudo systemctl status caduceus-gateway
```

## Configuration

Add to `.galaxy/config.json`:

```json
{
  "telegram_token": "...",
  "authorized_users": [123456789],
  "web": {
    "enabled": true,
    "port": 8080,
    "authorized_users": [123456789]
  }
}
```

## Design Philosophy

**Separation of Concerns**:
- Channels know platform APIs (Telegram, WebSocket)
- MessageBus knows message routing
- Executors know order processing
- Gateway knows lifecycle orchestration
- **No component knows about the others' internals**

**Filesystem Bridge**:
- Existing `.sisyphus/notepads/galaxy-orders/` protocol preserved
- HermesExecutor writes orders → Hermes daemon processes → responses appear
- Zero changes to hermes.py or galaxy_mcp.py

**Async-First**:
- All I/O is async (`async def`, `await`, `asyncio.Queue`)
- Channels run concurrently via `asyncio.gather`
- No blocking operations on main event loop

## Migration from bot.py

See `MIGRATION.md` for step-by-step guide.

**TL;DR**:
1. Keep bot.py running (don't stop it yet)
2. Start gateway.py (runs on different process)
3. Test both in parallel
4. Switch systemd service when confident
5. Archive bot.py

## Files

```
caduceus/
├── __init__.py           # Module exports
├── README.md             # This file
├── bus.py                # MessageBus + dataclasses
├── gateway.py            # Main entry point
├── channels/
│   ├── base.py           # BaseChannel ABC
│   ├── telegram.py       # TelegramChannel
│   └── web.py            # WebChannel
├── executors/
│   ├── base.py           # Executor ABC
│   └── hermes.py         # HermesExecutor
├── static/
│   ├── index.html        # Web UI
│   └── app.js            # WebSocket client
├── ARCHITECTURE.md       # Deep dive on design
├── MIGRATION.md          # Migration guide
└── examples/
    ├── telegram-only-config.json
    ├── web-only-config.json
    └── dual-channel-config.json
```

## References

- **nanobot**: Lightweight AI assistant with channel abstraction ([HKUDS/nanobot](https://github.com/HKUDS/nanobot))
- **asyncio.Queue**: Python async queue patterns
- **Galaxy Protocol**: Original Telegram bot (tools/bot.py, tools/hermes.py)

## License

Same as Galaxy Protocol (part of astraeus module ecosystem).
