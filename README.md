# Galaxy Protocol

> Remote control for [astraeus](https://github.com/rooftop-Owl/astraeus) — send orders from anywhere, get agent responses back.

## What It Does

Send a text message on Telegram → astraeus agent processes it → response sent back to Telegram.

Persistent sessions mean the agent remembers your conversation. Zero cost when idle.

## Phase 3 Features

- DeepWiki GitHub reference capture for repository URLs
- Voice message transcription via `faster-whisper`
- Image OCR and PDF extraction into `.sisyphus/references/`
- Multi-project routing using `#project` tags and keyword fallback
- Priority and scheduling markers (`🔴`, `🔵`, `⏰2h`)
- Optional digest push scheduler with SQLite persistence

## Setup

```bash
# 1. Load into your astraeus project
astraeus load galaxy-protocol

# 2. Create bot via @BotFather on Telegram
# 3. Configure
cp galaxy-protocol/tools/config.json.example .galaxy/config.json
# Edit with your telegram_token and authorized_users

# 4. Install deps
pip install -r galaxy-protocol/tools/requirements.txt

# Optional system deps for OCR/media
# Ubuntu/Debian: sudo apt install ffmpeg tesseract-ocr
# macOS: brew install ffmpeg tesseract

# 5. Run
python3 galaxy-protocol/tools/bot.py &
python3 galaxy-protocol/tools/hermes.py --interval 5 &

# Optional: validate enabled feature dependencies
python3 galaxy-protocol/tools/feature_preflight.py
```

## Architecture

```
Phone → Telegram → bot.py → order file → Hermes → opencode run → response → Telegram
```

## Components

| Component | Description |
|-----------|-------------|
| `tools/bot.py` | Telegram bot (any text = order) |
| `tools/hermes.py` | Order dispatcher (5s polling, 3min timeout, persistent sessions) |
| `tools/galaxy_mcp.py` | MCP server for programmatic access |
| `services/` | systemd units for production deployment |

## Requirements

- astraeus >= 0.3.0
- Python 3.10+
- `python-telegram-bot` (see requirements.txt)

## Feature Flags

Feature flags live in `.galaxy/config.json` under `features` and are disabled by default.

- `GALAXY_DEEPWIKI_ENABLED`
- `GALAXY_VOICE_ENABLED`
- `GALAXY_IMAGE_PDF_ENABLED`
- `GALAXY_MULTI_PROJECT_ENABLED`
- `GALAXY_PRIORITY_SCHEDULING_ENABLED`
- `GALAXY_DIGEST_PUSH_ENABLED`

## License

Same as astraeus.

## DeepWiki Diagnostic Digest

Transform GitHub repository references into actionable intelligence with architectural insights and adoption paths.

### Features

- **Deep Analysis**: Extracts architecture, design patterns, and core abstractions from GitHub repos via DeepWiki MCP
- **Diagnostic Intelligence**: Generates concrete adoption paths with complexity indicators (🟢🟡🔴)
- **Scheduled Push**: Daily 9 AM KST digest to Telegram (optional)
- **Backward Compatible**: Feature-flagged, falls back to shallow capture if disabled

### Configuration

Enable in `.galaxy/config.json`:

```json
{
  "features": {
    "GALAXY_DEEPWIKI_ENABLED": true,
    "GALAXY_DIGEST_PUSH_ENABLED": true
  }
}
```

### Usage

```bash
# Capture GitHub repo with deep analysis
/feed https://github.com/vercel/ai

# Generate diagnostic digest
/digest --last 7
```

### Complexity Indicators

| Indicator | Meaning | Criteria |
|-----------|---------|----------|
| 🟢 Easy | Quick win | ≤1 file, <2 hours, no deps |
| 🟡 Moderate | Planned effort | 2-5 files, 2-8 hours, minor deps |
| 🔴 Complex | Strategic initiative | >5 files, >8 hours, architectural |
