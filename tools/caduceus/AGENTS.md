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
- `executor_timeout`, `executor_poll_interval` for HermesExecutor.

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
