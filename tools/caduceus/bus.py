"""Message bus for routing between channels and executors.

This module defines the core message types and async routing infrastructure
for the Caduceus gateway. Messages flow through two async queues:

    Inbound:  Channel → publish_inbound() → Queue → consume_inbound() → Executor
    Outbound: Executor → publish_outbound() → Queue → consume_outbound() → Channel

InboundMessage captures user input from any channel (Telegram, web, etc.)
along with metadata for session tracking. OutboundMessage carries executor
responses back to the originating channel.

All queues are in-memory asyncio.Queue instances — no persistence layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class InboundMessage:
    """A message received from an external channel.

    Attributes:
        channel: Source channel identifier (e.g. "telegram", "web").
        sender_id: Unique identifier for the message sender.
        chat_id: Conversation/chat identifier within the channel.
        content: Text content of the message.
        media: Attached media objects (future: file attachments).
        metadata: Arbitrary key-value pairs for channel-specific data.
    """

    channel: str
    sender_id: str
    chat_id: str
    content: str
    media: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    user_id: str = ""

    @property
    def session_key(self) -> str:
        """Generate session key for continuity tracking.

        If user_id is set (authenticated), use it for cross-channel continuity.
        Otherwise fall back to channel-specific key.
        """
        if self.user_id:
            return self.user_id
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """A response message destined for an external channel.

    Attributes:
        channel: Target channel identifier (must match an active channel).
        chat_id: Conversation/chat to deliver the response to.
        content: Text content of the response.
    """

    channel: str
    chat_id: str
    content: str


class MessageBus:
    """Async message routing between channels and executors.

    The bus owns two independent asyncio queues that decouple message
    producers from consumers:

    * **inbound** — channels publish user messages; executors consume them.
    * **outbound** — executors publish responses; channels consume them.

    Architecture::

        Channel  ──publish_inbound()──►  inbound Queue  ──consume_inbound()──►  Executor
        Executor ──publish_outbound()──► outbound Queue  ──consume_outbound()──► Channel

    Usage::

        bus = MessageBus()

        # Channel side
        await bus.publish_inbound(msg)
        response = await bus.consume_outbound()

        # Executor side
        msg = await bus.consume_inbound()
        await bus.publish_outbound(response)
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a user message from a channel into the inbound queue.

        Args:
            msg: The inbound message to route to an executor.
        """
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next user message from the inbound queue.

        Blocks until a message is available.

        Returns:
            The next inbound message.
        """
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish an executor response into the outbound queue.

        Args:
            msg: The outbound message to route to a channel.
        """
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next response from the outbound queue.

        Blocks until a message is available.

        Returns:
            The next outbound message.
        """
        return await self.outbound.get()
