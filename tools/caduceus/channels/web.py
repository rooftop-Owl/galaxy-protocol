"""WebChannel - WebSocket-based chat interface."""

import asyncio
import importlib
import json
import logging
from typing import Any
from aiohttp import web, WSMsgType
from pathlib import Path

from .base import BaseChannel
from ..bus import OutboundMessage

session_tracker = importlib.import_module("session_tracker")
log_event = session_tracker.log_event

logger = logging.getLogger(__name__)


class WebChannel(BaseChannel):
    """Web-based chat channel using WebSockets.

    Serves a minimal chat UI at / and WebSocket endpoint at /ws.
    Requires JWT authentication via UserStore.
    """

    def __init__(self, config: dict[str, Any], bus, user_store):
        super().__init__(config, bus)
        if user_store is None:
            raise ValueError("WebChannel requires a UserStore instance")
        self.user_store = user_store
        self.port = config.get("port", 8080)
        self.secure_cookies = config.get("secure_cookies", False)
        self.connections: dict[str, web.WebSocketResponse] = {}
        self.app = None
        self.runner = None
        self.site = None

    async def start(self) -> None:
        """Start aiohttp web server."""
        self.app = web.Application()
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/login", self.handle_login_page)
        self.app.router.add_post("/login", self.handle_login)
        self.app.router.add_get("/logout", self.handle_logout)
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
        """Serve index.html (requires authentication)."""
        token = request.cookies.get("galaxy_token")
        if token:
            user_data = self.user_store.verify_token(token)
            if user_data:
                index_path = Path(__file__).parent.parent / "static" / "index.html"
                return web.FileResponse(index_path)
        raise web.HTTPFound("/login")

    async def handle_login_page(self, request):
        """Serve login.html."""
        login_path = Path(__file__).parent.parent / "static" / "login.html"
        return web.FileResponse(login_path)

    async def handle_login(self, request):
        """Authenticate user and set JWT cookie."""
        data = await request.post()
        username = data.get("username", "").strip()
        password = data.get("password", "")

        if self.user_store.verify_password(username, password):
            user = self.user_store.get_by_username(username)
            if user:
                token = self.user_store.create_token(user.id, user.username)
                log_event(
                    "frontend_login_success",
                    component="web",
                    user_id=user.id,
                    username=user.username,
                    remote=request.remote,
                )
                response = web.HTTPFound("/")
                response.set_cookie(
                    "galaxy_token",
                    token,
                    max_age=86400,
                    httponly=True,
                    secure=self.secure_cookies,
                    samesite="Lax",
                )
                return response

        log_event(
            "frontend_login_failed",
            component="web",
            username=username,
            remote=request.remote,
        )
        return web.json_response(
            {"error": "Invalid credentials"},
            status=401,
        )

    async def handle_logout(self, request):
        """Clear JWT cookie and redirect to login."""
        response = web.HTTPFound("/login")
        response.del_cookie("galaxy_token")
        return response

    async def handle_websocket(self, request):
        """WebSocket handler (requires authentication)."""
        ws = web.WebSocketResponse(autoping=True, heartbeat=5.0)
        await ws.prepare(request)

        token = request.cookies.get("galaxy_token")
        logger.debug(f"WebSocket auth: token={'present' if token else 'missing'}")

        user_data = None
        if token:
            try:
                user_data = self.user_store.verify_token(token)
                logger.debug(
                    f"Token verification: {('success: ' + user_data['user_id']) if user_data else 'failed'}"
                )
            except Exception as e:
                logger.error(f"Token verification error: {e}", exc_info=True)

        if not user_data:
            logger.warning(f"WebSocket auth failed for {request.remote}")
            log_event(
                "frontend_ws_auth_failed",
                component="web",
                remote=request.remote,
            )
            await ws.send_json(
                {"type": "error", "content": "Unauthorized - please login"}
            )
            await ws.close()
            return ws

        user_id = user_data["user_id"]
        chat_id = user_id
        sender_id = user_id
        logger.debug(f"WebSocket user_id: {user_id}")

        old_ws = self.connections.get(chat_id)
        if old_ws and not old_ws.closed:
            log_event(
                "frontend_ws_replaced",
                component="web",
                user_id=user_id,
                username=user_data["username"],
                chat_id=chat_id,
                remote=request.remote,
            )
            logger.debug(f"Closing old WebSocket for {chat_id}")
            await old_ws.send_json(
                {"type": "system", "content": "Session replaced by new connection"}
            )
            await old_ws.close()

        self.connections[chat_id] = ws
        log_event(
            "frontend_ws_connected",
            component="web",
            user_id=user_id,
            username=user_data["username"],
            chat_id=chat_id,
            remote=request.remote,
        )
        logger.debug(f"Added WebSocket to connections: {chat_id}")

        logger.debug(f"Sending welcome message to {chat_id}")
        await ws.send_json(
            {
                "type": "system",
                "content": f"Connected as {user_data['username']}",
                "chat_id": chat_id,
            }
        )
        logger.debug(f"Welcome message sent, entering message loop")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    content = data.get("content", "")

                    await self._handle_message(
                        sender_id=sender_id,
                        chat_id=chat_id,
                        content=content,
                        metadata={"source": "web", "username": user_data["username"]},
                        user_id=user_id,
                    )

                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")

        except Exception as e:
            logger.error(
                f"WebSocket message loop error for {chat_id}: {e}", exc_info=True
            )
            log_event(
                "frontend_ws_error",
                component="web",
                user_id=user_id,
                username=user_data["username"],
                chat_id=chat_id,
                error=str(e),
            )
        finally:
            logger.debug(f"WebSocket loop exited for {chat_id}, closed={ws.closed}")
            self.connections.pop(chat_id, None)
            log_event(
                "frontend_ws_disconnected",
                component="web",
                user_id=user_id,
                username=user_data["username"],
                chat_id=chat_id,
            )

        return ws
