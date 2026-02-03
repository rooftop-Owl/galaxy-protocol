"""Base channel interface for Caduceus gateway.

All channel implementations (Telegram, Web, etc.) must inherit from BaseChannel.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

from caduceus.bus import MessageBus, InboundMessage, OutboundMessage


class BaseChannel(ABC):
    """Abstract base class for all channel implementations.

    Channels are platform-specific frontends (Telegram, Web, Discord, etc.)
    that convert platform messages into InboundMessage and vice versa.

    Architecture:
        User → Channel.start() → _handle_message() → MessageBus → Executor
        Executor → MessageBus → Channel.send() → User
    """

    def __init__(self, config: Dict[str, Any], bus: MessageBus):
        """Initialize channel with config and message bus.

        Args:
            config: Platform-specific configuration (tokens, URLs, etc.)
            bus: MessageBus instance for routing messages
        """
        self.config = config
        self.bus = bus

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (connect to platform, begin polling, etc.).

        Platform-specific implementation. Must be idempotent.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel gracefully (disconnect, cleanup resources).

        Platform-specific implementation. Must be idempotent.
        """
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send message to user via platform-specific API.

        Args:
            msg: OutboundMessage with channel, chat_id, content

        Platform-specific implementation.
        """
        pass

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Generic message handler - creates InboundMessage and publishes to bus.

        Call this from platform-specific message handlers to route messages
        through the gateway.

        Args:
            sender_id: Platform-specific user ID
            chat_id: Platform-specific chat/conversation ID
            content: Message text content
            media: Optional list of media attachments
            metadata: Optional platform-specific metadata
        """
        msg = InboundMessage(
            channel=self.__class__.__name__.replace("Channel", "").lower(),
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=metadata or {},
        )
        await self.bus.publish_inbound(msg)
