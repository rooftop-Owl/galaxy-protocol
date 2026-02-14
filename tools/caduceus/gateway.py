#!/usr/bin/env python3
"""Caduceus Gateway — Unified multi-channel entry point.

Routes messages between channels (Telegram, Web) and executors (Hermes)
via an async MessageBus.

Usage:
    python3 gateway.py --config .galaxy/config.json
    python3 gateway.py --config .galaxy/config.json --log-level DEBUG
    python3 gateway.py --test-mode --config config.json.example

Architecture:
    Channel → MessageBus.inbound → executor_loop → MessageBus.outbound → outbound_dispatcher → Channel
"""

import argparse
import asyncio
import importlib
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

# Ensure caduceus package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

auth_store_mod = importlib.import_module("caduceus.auth.store")
bus_mod = importlib.import_module("caduceus.bus")
telegram_mod = importlib.import_module("caduceus.channels.telegram")
web_mod = importlib.import_module("caduceus.channels.web")
executor_mod = importlib.import_module("caduceus.executors.hermes")

UserStore = auth_store_mod.UserStore
MessageBus = bus_mod.MessageBus
OutboundMessage = bus_mod.OutboundMessage
TelegramChannel = telegram_mod.TelegramChannel
WebChannel = web_mod.WebChannel
HermesExecutor = executor_mod.HermesExecutor

session_tracker = importlib.import_module("session_tracker")
log_event = session_tracker.log_event

logger = logging.getLogger("caduceus.gateway")


async def executor_loop(
    bus: MessageBus, executor: HermesExecutor, channels: dict[str, Any]
):
    """Consume inbound messages, execute, publish outbound responses.

    Args:
        bus: MessageBus instance
        executor: HermesExecutor to process orders
        channels: Dict of {name: channel} for response routing
    """
    while True:
        msg = await bus.consume_inbound()
        logger.info(f"Processing: [{msg.channel}:{msg.chat_id}] {msg.content[:80]}")

        try:
            result = await executor.execute(
                {
                    "payload": msg.content,
                    "timestamp": 0,
                    "order_id": msg.session_key,
                    "sender_id": msg.sender_id,
                    "chat_id": msg.chat_id,
                    "channel": msg.channel,
                }
            )

            if result.get("success") and result.get("response_text"):
                response = OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=result["response_text"],
                )
                await bus.publish_outbound(response)
            elif result.get("error"):
                logger.error(f"Execution error: {result['error']}")

        except Exception as e:
            logger.error(f"Executor loop error: {e}", exc_info=True)


async def outbound_dispatcher(bus: MessageBus, channels: dict[str, Any]):
    """Consume outbound messages and route to appropriate channel.

    Args:
        bus: MessageBus instance
        channels: Dict of {name: channel} for message delivery
    """
    while True:
        msg = await bus.consume_outbound()

        channel = channels.get(msg.channel)
        if channel:
            try:
                await channel.send(msg)
                logger.debug(f"Dispatched to {msg.channel}: {msg.content[:80]}")
            except Exception as e:
                logger.error(f"Dispatch error [{msg.channel}]: {e}")
        else:
            logger.warning(f"No channel '{msg.channel}' for outbound message")


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config not found at {path}")
        print("Copy tools/config.json.example to .galaxy/config.json")
        sys.exit(1)

    with open(path) as f:
        return json.load(f)


def build_channels(config: dict[str, Any], bus: MessageBus) -> dict[str, Any]:
    """Instantiate channels based on configuration.

    Returns dict of {channel_name: channel_instance}.
    """
    channels = {}

    auth_config = config.get("auth", {})
    jwt_secret = auth_config.get("jwt_secret", "")
    if not jwt_secret:
        logger.warning(
            "auth.jwt_secret not configured — web authentication will not work"
        )

    user_store = UserStore(
        db_path=auth_config.get("db_path", ".galaxy/users.db"),
        jwt_secret=jwt_secret,
        token_expiry_hours=auth_config.get("token_expiry_hours", 24),
    )
    logger.info(
        f"UserStore initialized: {auth_config.get('db_path', '.galaxy/users.db')}"
    )

    token = config.get("telegram_token", "")
    if token and "CHANGE-ME" not in token:
        channels["telegram"] = TelegramChannel(config, bus, user_store)
        logger.info("Telegram channel enabled")

    web_config = config.get("web", {})
    if web_config.get("enabled", False):
        channels["web"] = WebChannel(web_config, bus, user_store)
        logger.info(f"Web channel enabled on port {web_config.get('port', 8080)}")

    return channels


async def run_gateway(config: dict[str, Any], test_mode: bool = False):
    """Main gateway coroutine.

    Args:
        config: Configuration dictionary
        test_mode: If True, validate config and exit without starting
    """
    bus = MessageBus()
    channels = build_channels(config, bus)

    if not channels:
        logger.error("No channels configured. Check config.json.")
        logger.error("Need telegram_token or web.enabled=true")
        return

    # Build executor
    # PHASE 1: Testing locally in submodule (use current working directory)
    # PHASE 2: Production (use config.get("repo_path") when running from parent)
    repo_root = Path.cwd()  # Current directory for Phase 1 testing
    executor_config = {
        "orders_dir": str(repo_root / ".sisyphus" / "notepads" / "galaxy-orders"),
        "timeout": config.get("executor_timeout", 180),
        "poll_interval": config.get("executor_poll_interval", 1.0),
    }
    executor = HermesExecutor(executor_config)

    log_event(
        "daemon_started",
        component="caduceus-gateway",
        channels=list(channels.keys()),
        orders_dir=executor_config["orders_dir"],
    )

    if test_mode:
        channel_names = ", ".join(channels.keys())
        print(f"Caduceus gateway — test mode")
        print(f"  Channels: {channel_names}")
        print(f"  Executor: HermesExecutor")
        print(f"  Orders dir: {executor_config['orders_dir']}")
        print("Config valid. Exiting test mode.")
        return

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start all channels
    channel_names = ", ".join(channels.keys())
    logger.info(f"🏥 Caduceus gateway starting — channels: {channel_names}")

    tasks = []
    try:
        # Start channels
        for name, channel in channels.items():
            await channel.start()
            logger.info(f"  ✓ {name} channel started")

        # Start background loops
        tasks.append(asyncio.create_task(executor_loop(bus, executor, channels)))
        tasks.append(asyncio.create_task(outbound_dispatcher(bus, channels)))

        logger.info("🏥 Caduceus gateway online")

        # Wait for shutdown signal
        await shutdown_event.wait()

    finally:
        logger.info("Shutting down...")
        log_event(
            "daemon_stopped",
            component="caduceus-gateway",
            channels=list(channels.keys()),
        )

        # Cancel background tasks
        for task in tasks:
            task.cancel()

        # Stop channels
        for name, channel in channels.items():
            try:
                await channel.stop()
                logger.info(f"  ✓ {name} channel stopped")
            except Exception as e:
                logger.error(f"  ✗ {name} stop error: {e}")

        logger.info("🏥 Caduceus gateway offline")


def main():
    parser = argparse.ArgumentParser(
        prog="caduceus-gateway",
        description="Caduceus — Multi-channel gateway for Galaxy Protocol",
        usage="%(prog)s [options]",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(
            Path(__file__).parent.parent.parent.parent / ".galaxy" / "config.json"
        ),
        help="Path to config.json (default: .galaxy/config.json)",
    )
    parser.add_argument(
        "--test-mode",
        "-t",
        action="store_true",
        help="Validate config and exit without starting",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config(args.config)

    try:
        asyncio.run(run_gateway(config, test_mode=args.test_mode))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
