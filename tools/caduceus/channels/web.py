"""WebChannel - WebSocket-based chat interface."""

import asyncio
import json
import logging
from typing import Dict
from aiohttp import web, WSMsgType
from pathlib import Path

from caduceus.channels.base import BaseChannel
from caduceus.bus import OutboundMessage

logger = logging.getLogger(__name__)


class WebChannel(BaseChannel):
    """Web-based chat channel using WebSockets.

    Serves a minimal chat UI at / and WebSocket endpoint at /ws.
    """

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.port = config.get("port", 8080)
        self.authorized_users = config.get("authorized_users", [])
        self.connections: Dict[str, web.WebSocketResponse] = {}
        self.app = None
        self.runner = None
        self.site = None

    async def start(self) -> None:
        """Start aiohttp web server."""
        self.app = web.Application()
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/ws", self.handle_websocket)
        self.app.router.add_static("/static", Path(__file__).parent.parent / "static")

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await self.site.start()
        logger.info(f"WebChannel started on port {self.port}")

    async def stop(self) -> None:
        """Stop web server gracefully."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("WebChannel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send message to WebSocket client."""
        ws = self.connections.get(msg.chat_id)
        if ws and not ws.closed:
            await ws.send_json(
                {
                    "type": "message",
                    "content": msg.content,
                    "timestamp": asyncio.get_event_loop().time(),
                }
            )
        else:
            logger.warning(f"No active WebSocket for chat_id={msg.chat_id}")

    async def handle_index(self, request):
        """Serve index.html."""
        index_path = Path(__file__).parent.parent / "static" / "index.html"
        return web.FileResponse(index_path)

    async def handle_websocket(self, request):
        """WebSocket handler."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Generate chat_id from connection
        chat_id = f"web-{id(ws)}"
        self.connections[chat_id] = ws

        # Send welcome message
        await ws.send_json(
            {"type": "system", "content": f"Connected as {chat_id}", "chat_id": chat_id}
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    content = data.get("content", "")
                    sender_id = data.get("sender_id", chat_id)

                    # Authorization check
                    if self.authorized_users and sender_id not in self.authorized_users:
                        await ws.send_json({"type": "error", "content": "Unauthorized"})
                        continue

                    # Publish to bus
                    await self._handle_message(
                        sender_id=sender_id,
                        chat_id=chat_id,
                        content=content,
                        metadata={"source": "web"},
                    )

                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")

        finally:
            self.connections.pop(chat_id, None)

        return ws
