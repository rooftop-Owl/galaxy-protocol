"""
Caduceus — The Gateway That Gives Hermes Wings

A multi-channel gateway for Galaxy Protocol, following nanobot's proven architecture patterns.

Architecture:
    Channel (frontend) → MessageBus → Executor (backend) → MessageBus → Channel

Components:
    - BaseChannel: Abstract interface for chat platforms (Telegram, Web, etc.)
    - MessageBus: Async queue-based message routing (inbound/outbound)
    - Executor: Abstract interface for order execution backends
    - Gateway: Orchestrates channels + executors via asyncio

Design Philosophy:
    - Channels decouple frontends from agent core
    - MessageBus provides platform-agnostic message routing
    - Executors abstract execution environments (Hermes, sandbox, etc.)
    - Gateway coordinates all components with graceful lifecycle management

Inspired by:
    - HKUDS/nanobot's channel abstraction pattern
    - Event-driven architecture with asyncio.Queue
    - Filesystem order protocol as integration bridge

Usage:
    from caduceus.gateway import Gateway
    from caduceus.channels.telegram import TelegramChannel
    from caduceus.channels.web import WebChannel

    # See gateway.py for full orchestration example
"""

__version__ = "0.1.0"
__author__ = "Galaxy Protocol Team"

# Core components
from .bus import MessageBus, InboundMessage, OutboundMessage

# Base abstractions
from .channels.base import BaseChannel
from .executors.base import Executor

__all__ = [
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
    "BaseChannel",
    "Executor",
]
