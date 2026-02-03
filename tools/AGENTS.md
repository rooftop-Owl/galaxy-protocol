# Galaxy Protocol

## OVERVIEW
Multi-machine agent communication: Telegram bot + MCP server + order/outbox system.

## STRUCTURE
```
galaxy/
├── bot.py                # Telegram bot — /status, /order, /concerns, /machines
├── galaxy_mcp.py         # Galaxy MCP server — processes orders from agents
├── config.json.example   # Config template (tokens, machines, topics)
├── notify.sh             # ntfy.sh notification helper
├── stars-sync.sh         # GitHub star list sync
├── stars.json            # Star list state
├── requirements.txt      # Python deps (python-telegram-bot)
├── galaxy.service        # systemd unit for bot
├── galaxy-mcp.service    # systemd unit for MCP server
└── test_phase_c_e2e.py   # E2E tests for Galaxy Phase C
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Start bot | `bot.py` | Needs `config.json` (copy from example) |
| Process orders | `galaxy_mcp.py` | Reads `.sisyphus/notepads/galaxy-orders/` |
| Configure machines | `config.json.example` | Define machine IDs, tokens, topics |
| Run as service | `galaxy.service` | systemd: `systemctl start galaxy` |

## CONVENTIONS
- **Order flow**: User → Telegram → `galaxy-orders/*.json` → agent picks up → response
- **Outbox**: Agents write to `galaxy-outbox/` for proactive notifications
- **Config**: Copy `config.json.example` → `config.json`, never commit real tokens
- **Testing**: `pytest test_phase_c_e2e.py` for integration tests

## ANTI-PATTERNS
- **NEVER** commit `config.json` (contains tokens)
- **NEVER** create orders from agents (user-initiated only)
- **NEVER** modify order JSON schema without updating bot + MCP
