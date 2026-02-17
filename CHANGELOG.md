# Changelog

All notable changes to Galaxy Protocol will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **Caduceus Gateway** - Multi-channel messaging gateway replacing bot.py
  - BaseChannel + MessageBus + Executor architecture pattern
  - TelegramChannel: Full Telegram Bot API integration (769 lines)
  - WebChannel: WebSocket server with dark-themed UI, mobile-responsive
  - HermesExecutor: Filesystem bridge to hermes.py via order protocol
  - 34 unit tests (100% passing)
  - Production-verified: Telegram, web UI (localhost + mobile), concurrent messages, resource cleanup
  - Phase 1 testing mode: Local submodule execution with MODULE_ROOT paths
  - Documentation: ARCHITECTURE.md, MIGRATION.md, README.md, 3 example configs

### Changed
- hermes.py: Self-directed memory (reads history on demand, not pre-stuffed)
- hermes.py, caduceus/executors/hermes.py, caduceus/gateway.py: Raised execution timeout 180s → 600s (10 min), configurable via `executor_timeout` in `.galaxy/config.json`. Note: galaxy_mcp.py D1 path intentionally remains at 300s (MCP tool call context).
- hermes.py: Territory sandbox (workspace constraints in prompt)

### Fixed
- Import paths: All channels/executors use absolute imports with sys.path.insert
- Web auth: Skip authorization check for dynamically generated web-* IDs (localhost)
- Path resolution: Phase 1 uses MODULE_ROOT for submodule testing, Phase 2 will revert to REPO_ROOT

---

## [0.1.0] - 2026-02-02

### Added
- Initial extraction from astraeus parent repository
- Galaxy Protocol as 4th astraeus module
- GPU cluster documentation (2,747 lines, 7 docs)
- Module commands and rules support

### Infrastructure
- Registered as astraeus module with load/unload support
- Git submodule configuration
- Module-specific .claude/ directory structure

---

[Unreleased]: https://github.com/yourusername/galaxy-protocol/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/galaxy-protocol/releases/tag/v0.1.0
