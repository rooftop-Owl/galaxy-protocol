# Caduceus Channels

## OVERVIEW
- Platform adapters: translate platform events to `InboundMessage`, deliver `OutboundMessage`.

## STRUCTURE
```
channels/
├── base.py
├── telegram.py
└── web.py
```

## BASECHANNEL CONTRACT
- `start()` / `stop()` / `send(msg)` must be idempotent.
- `_handle_message(...)` publishes to MessageBus; channel name derived from class.

## TELEGRAMCHANNEL (telegram.py)
- python-telegram-bot `ApplicationBuilder` with command handlers.
- Config keys: `telegram_token`, `authorized_users`, `machines`, `default_machine`, `poll_interval`.
- Writes local order JSON to `.sisyphus/notepads/galaxy-orders` and publishes to bus.
- Background polling: order acknowledgments + `galaxy-outbox` messages.
- `format_response_compact` renders HTML + emoji; 1500 char cap.

## WEBCHANNEL (web.py)
- aiohttp server: `/`, `/login`, `/logout`, `/ws`, `/static`.
- Requires `UserStore`; JWT cookie `galaxy_token` gate.
- Single active websocket per user; `connections` keyed by chat_id.
- `web.secure_cookies` toggles cookie security.

## CONVENTIONS
- Use `metadata.source` = `telegram` or `web`.
- Web chat_id == user_id for session continuity.
- Authenticate before websocket accept; close on failure.

## ANTI-PATTERNS
- Avoid blocking subprocess calls on the event loop.
- Do not call executors directly; always publish via MessageBus.
- Do not change order schema or response formatting without Hermes alignment.
