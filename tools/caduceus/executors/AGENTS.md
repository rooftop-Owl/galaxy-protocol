# Caduceus Executors

## OVERVIEW
- Execution backends for Caduceus; currently Hermes filesystem bridge.

## STRUCTURE
```
executors/
├── base.py
└── hermes.py
```

## EXECUTOR CONTRACT
- `execute(order: dict) -> dict` async.
- Return `success`, `response_text`, optional `error`.
- Expect `payload`, `timestamp`, `order_id` plus channel metadata.

## HERMES EXECUTOR
- Writes order JSON into `.sisyphus/notepads/galaxy-orders/`.
- Waits for `.sisyphus/notepads/galaxy-order-response-{order_id}.md`.
- Cleans response file after read; removes order file on timeout.

## CONFIG KEYS
- `orders_dir` (default `.sisyphus/notepads/galaxy-orders`).
- `timeout` (default 180s).
- `poll_interval` (default 1.0s).

## CONVENTIONS
- `order_id` comes from MessageBus `session_key`.
- Response text is raw markdown; formatting belongs to channel.
- Use async sleep for polling.

## ANTI-PATTERNS
- Do not change response filename pattern without updating hermes.py.
- Avoid writing to unrelated notepads here.
- No blocking loops or busy-wait.
