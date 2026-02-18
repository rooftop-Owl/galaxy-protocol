# Galaxy Protocol

## OVERVIEW
Multi-machine agent communication: Telegram/Web gateway + MCP server + order/outbox system.

## STRUCTURE
```
galaxy/
├── caduceus/             # Multi-channel gateway (Telegram + Web)
│   ├── gateway.py        # Entry point — start this, not bot.py
│   ├── channels/
│   │   ├── telegram.py   # TelegramChannel (bot commands, digest scheduler)
│   │   └── web.py        # WebChannel (WebSocket)
│   └── executors/
│       └── hermes.py     # HermesExecutor (filesystem bridge)
├── galaxy_mcp.py         # Galaxy MCP server — processes orders from agents
├── config.json.example   # Config template (tokens, machines, topics)
├── requirements.txt      # Python deps (python-telegram-bot, apscheduler)
└── test_phase_c_e2e.py   # E2E tests for Galaxy Phase C
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Start gateway | `caduceus/gateway.py` | Needs `config.json` (copy from example) |
| Telegram commands | `caduceus/channels/telegram.py` | All handlers + digest scheduler |
| Daily digest push | `caduceus/channels/telegram.py` | `_load_latest_digest` + `setup_digest_scheduler` wired in `start()` |
| Process orders | `galaxy_mcp.py` | Reads `.sisyphus/notepads/galaxy-orders/` |
| Configure machines | `config.json.example` | Define machine IDs, tokens, topics |
| Run as service | `services/caduceus-gateway.service` | systemd: `systemctl start caduceus-gateway` |

## CONVENTIONS
- **Order flow**: User → Telegram/Web → `galaxy-orders/*.json` → agent picks up → response
- **Outbox**: Agents write to `galaxy-outbox/` for proactive notifications
- **Config**: Copy `config.json.example` → `config.json`, never commit real tokens
- **Digest push**: Enabled via `features.GALAXY_DIGEST_PUSH_ENABLED` in config; fires 9 AM KST
- **Testing**: `pytest test_phase_c_e2e.py` for integration tests

## ANTI-PATTERNS
- **NEVER** use `bot.py` — it is deleted; the gateway is `caduceus/gateway.py`
- **NEVER** commit `config.json` (contains tokens)
- **NEVER** create orders from agents (user-initiated only)
- **NEVER** modify order JSON schema without updating gateway + MCP
