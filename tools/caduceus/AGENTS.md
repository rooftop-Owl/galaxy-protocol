# Caduceus Gateway

## OVERVIEW
- Multi-channel gateway runtime; async MessageBus + HermesExecutor filesystem bridge.
- Entry point for Telegram + Web channels; routing only, no business logic.

## ENTRYPOINTS
- `gateway.py` CLI: `--config`, `--test-mode`, `--log-level`.
- `install-service.sh` installs the systemd unit for the gateway.

## CORE OBJECTS
- `bus.py`: `MessageBus`, `InboundMessage`, `OutboundMessage`.
- `gateway.executor_loop` consumes inbound; `outbound_dispatcher` routes outbound.
- `executors/hermes.py` handles order execution.

## CONFIG
- `.galaxy/config.json` (default path from gateway).
- `auth.jwt_secret`, `auth.db_path`, `auth.token_expiry_hours` for UserStore.
- `telegram_token`, `authorized_users`, `machines`, `default_machine`, `poll_interval`.
- `web.enabled`, `web.port`, `web.secure_cookies`.
- `executor_timeout` (default 600s = 10 min), `executor_poll_interval` for HermesExecutor.

## RUNTIME FLOW
- Build MessageBus + channels; start channels before background loops.
- Background tasks: `executor_loop` + `outbound_dispatcher`.
- Shutdown via SIGINT/SIGTERM; cancel tasks then stop channels.

## CONVENTIONS
- Keep queues in-memory; no persistence in MessageBus.
- Order id = `session_key` (`{channel}:{chat_id}`) for continuity.
- Gateway does not write orders directly; executor owns `.sisyphus/notepads/galaxy-orders`.

## WHERE TO LOOK
- `gateway.py` lifecycle, signal handling, test-mode validation.
- `bus.py` message schema + queues.
- `auth/store.py` JWT + SQLite users (`.galaxy/users.db`).

## ANTI-PATTERNS
- No blocking file or subprocess I/O inside gateway loops.
- Do not instantiate channels without config guardrails.
- Avoid mixing channel-specific logic into gateway.

## Liveness Notifications (galaxy-outbox/)

Two notification patterns written during order execution:

| Pattern | Written By | When | Routed By |
|---------|-----------|------|-----------|
| `processing-{order_id}.json` | HermesExecutor, hermes.py | Order claimed | poll_outbox_messages (chat_id routing) |
| `heartbeat-{order_id}-{elapsed}.json` | HermesExecutor only | Every 60s after 1st minute | poll_outbox_messages (chat_id routing) |

Both are cleaned up on order completion or timeout. Routing uses existing chat_id field at telegram.py:697-699.
