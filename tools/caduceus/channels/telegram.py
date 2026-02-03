"""TelegramChannel - Telegram bot interface for Caduceus gateway.

Extracted from bot.py. Preserves ALL existing functionality:
- Authorization checks
- Order creation via filesystem protocol
- Command handlers (/status, /concerns, /order, /machines, /help)
- Background polling (order acknowledgments, outbox messages)
- Response formatting (compact emoji format)
- Machine resolution (multi-machine support)
"""

import json
import glob
import shlex
import subprocess
import asyncio
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Set

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

from caduceus.channels.base import BaseChannel
from caduceus.bus import MessageBus, OutboundMessage

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """Telegram bot channel implementation.

    Wraps all functionality from the original bot.py into a BaseChannel
    subclass while preserving exact behavior.

    Config keys:
        telegram_token (str): Bot token from @BotFather
        authorized_users (list[int]): Authorized Telegram user IDs
        machines (dict): Machine registry
        default_machine (str): Default machine name
        poll_interval (int): Polling interval in seconds (default: 30)
    """

    def __init__(self, config: Dict[str, Any], bus: MessageBus):
        super().__init__(config, bus)

        self.token = config["telegram_token"]
        self.authorized: Set[int] = set(config.get("authorized_users", []))
        self.machines = self._load_machines(config)
        self.default_machine = config.get(
            "default_machine", next(iter(self.machines))
        )
        self.poll_interval = config.get("poll_interval", 30)

        # Track pending orders for acknowledgment polling
        self.pending_orders: Dict[str, Dict] = {}

        self.app = None

    # --- MACHINE REGISTRY ---

    @staticmethod
    def _load_machines(config: Dict) -> Dict[str, Dict]:
        """Load machine registry from config.

        Supports two formats:
        - New: { "machines": { "lab": { "host": "localhost", "repo_path": "..." } } }
        - Legacy: { "machine_name": "lab", "repo_path": "..." }

        Returns dict of { name: { host, repo_path, machine_name } }
        """
        if "machines" in config:
            machines = {}
            for name, entry in config["machines"].items():
                machines[name] = {
                    "host": entry.get("host", "localhost"),
                    "repo_path": Path(entry["repo_path"]),
                    "machine_name": entry.get("machine_name", name),
                }
            return machines

        # Legacy single-machine format
        name = config.get("machine_name", "local")
        return {
            name: {
                "host": "localhost",
                "repo_path": Path(
                    config.get("repo_path", str(Path(__file__).parent.parent.parent.parent))
                ),
                "machine_name": name,
            }
        }

    # --- AUTH ---

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized

    # --- FORMATTING ---

    @staticmethod
    def format_response_compact(text: str) -> str:
        """Convert markdown response to compact emoji-rich format for Telegram HTML."""
        lines = text.strip().split("\n")
        output = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Convert markdown headers to emoji sections
            if line.startswith("# "):
                output.append(f"<b>🎯 {line[2:]}</b>")
            elif line.startswith("## "):
                output.append(f"<b>📌 {line[3:]}</b>")
            elif line.startswith("### "):
                output.append(f"<b>▪️ {line[4:]}</b>")
            # Convert bold
            elif "**" in line:
                line = line.replace("**", "<b>", 1).replace("**", "</b>", 1)
                output.append(line)
            # Convert status indicators
            elif line.startswith("- ✅") or line.startswith("✅"):
                output.append(line)
            elif line.startswith("- ❌") or line.startswith("❌"):
                output.append(line)
            elif line.startswith("- "):
                output.append(f"  {line[2:]}")  # Indent bullets
            # Skip markdown separators
            elif line == "---":
                continue
            # Keep everything else
            else:
                output.append(line)

        # Join with single newlines, collapse multiple blanks
        result = "\n".join(output)
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result[:1500]  # Hard cap for sanity

    # --- MACHINE HELPERS ---

    def resolve_machine(self, name: Optional[str]):
        """Resolve a machine name. Returns (machine_name, machine_config) or (None, None)."""
        if name is None:
            return self.default_machine, self.machines[self.default_machine]
        if name in self.machines:
            return name, self.machines[name]
        return None, None

    @staticmethod
    def is_local(machine: Dict) -> bool:
        """Check if a machine config points to localhost."""
        return machine["host"] in ("localhost", "127.0.0.1", "")

    @staticmethod
    def run_on_machine(machine: Dict, cmd: list):
        """Run a command on a machine. Local = subprocess, remote = ssh.

        Returns (stdout, stderr, returncode).
        """
        repo = str(machine["repo_path"])

        if TelegramChannel.is_local(machine):
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=repo, timeout=30
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode

        # Remote: SSH
        host = machine["host"]
        ssh_user = machine.get("ssh_user", "")
        target = f"{ssh_user}@{host}" if ssh_user else host
        ssh_cmd = [
            "ssh", "-o", "ConnectTimeout=5", target,
            f"cd {shlex.quote(str(repo))} && {' '.join(shlex.quote(c) for c in cmd)}"
        ]

        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip(), result.stderr.strip(), result.returncode

    # --- STATUS HELPERS ---

    def get_status_text(self, name: str, machine: Dict) -> str:
        """Build status text for a single machine."""
        try:
            git_log, _, _ = self.run_on_machine(machine, ["git", "log", "--oneline", "-5"])
        except Exception:
            git_log = "(git unavailable)"

        try:
            git_status, _, _ = self.run_on_machine(machine, ["git", "status", "--short"])
            git_status = git_status or "(clean)"
        except Exception:
            git_status = "(unknown)"

        try:
            stdout, _, _ = self.run_on_machine(
                machine, ["python3", "-m", "pytest", "tests/", "-q", "--tb=no"]
            )
            test_line = stdout.split("\n")[-1] if stdout else "unknown"
        except Exception:
            test_line = "(pytest unavailable)"

        # Stargazer reports (local only)
        report_summary = "No reports"
        if self.is_local(machine):
            repo = machine["repo_path"]
            reports = sorted(
                glob.glob(str(repo / ".sisyphus/notepads/stargazer-*/meta.json"))
            )
            if reports:
                report_summary = f"{len(reports)} report(s)"
                try:
                    with open(reports[-1]) as f:
                        latest = json.load(f)
                    critical = latest.get("critical_concerns", 0)
                    warnings = latest.get("warning_concerns", 0)
                    report_summary += f"\nLatest: {critical} critical, {warnings} warnings"
                except Exception:
                    pass

        return (
            f"📊 *{name}* Status\n\n"
            f"*Recent commits:*\n```\n{git_log}\n```\n\n"
            f"*Working tree:* `{git_status}`\n"
            f"*Tests:* {test_line}\n"
            f"*Stargazer:* {report_summary}\n"
            f"*Time:* {datetime.now().strftime('%H:%M:%S')}"
        )

    def get_concerns_text(self, name: str, machine: Dict) -> str:
        """Get concerns text for a single machine (local only)."""
        if not self.is_local(machine):
            return f"⚠️ *{name}*: concerns only available for local machines"

        repo = machine["repo_path"]
        problems_files = sorted(
            glob.glob(str(repo / ".sisyphus/notepads/stargazer-*/problems.md"))
        )

        if not problems_files:
            return f"✅ *{name}*: No Stargazer concerns on file."

        with open(problems_files[-1]) as f:
            content = f.read()

        if len(content) > 3500:
            content = content[:3500] + "\n\n... (truncated, see full in notepads)"

        return f"📋 *{name}* — Latest Concerns\n\n{content}"

    # --- ORDER HELPERS ---

    def create_order(self, machine_name: str, machine_config: Dict,
                     order_text: str, chat_id: int) -> Optional[str]:
        """Write an order JSON file. Returns the order file path or None."""
        if not self.is_local(machine_config):
            return None

        orders_dir = machine_config["repo_path"] / ".sisyphus" / "notepads" / "galaxy-orders"
        orders_dir.mkdir(parents=True, exist_ok=True)

        order = {
            "type": "galaxy_order",
            "from": "galaxy-gazer",
            "target": machine_name,
            "command": "general",
            "payload": order_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        order_file = orders_dir / f"{ts}.json"
        with open(order_file, "w") as f:
            json.dump(order, f, indent=2)

        return str(order_file)

    # --- TELEGRAM HANDLERS ---

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Any plain text message = order for default machine."""
        if not self.is_authorized(update.effective_user.id):
            return

        order_text = update.message.text.strip()
        if not order_text:
            return

        name = self.default_machine
        machine = self.machines[name]
        order_file = self.create_order(name, machine, order_text, update.effective_chat.id)

        if order_file:
            self.pending_orders[order_file] = {
                "machine": name,
                "chat_id": update.effective_chat.id,
                "order_text": order_text,
            }
            await update.message.reply_text(f"\U0001f4e1 \u2192 *{name}*", parse_mode="Markdown")

        # Also publish to MessageBus for gateway routing
        await self._handle_message(
            sender_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            content=order_text,
            metadata={"source": "telegram", "machine": name},
        )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Get machine status. Usage: /status [machine|all]"""
        user_id = update.effective_user.id
        if not self.is_authorized(user_id):
            await update.message.reply_text(
                f"❌ Unauthorized\n"
                f"Your Telegram user ID: `{user_id}`\n\n"
                f"Add this to `.galaxy/config.json`:\n"
                f'"authorized_users": [{user_id}]`',
                parse_mode="Markdown",
            )
            return

        target = ctx.args[0] if ctx.args else None

        if target == "all":
            parts = []
            for name, machine in self.machines.items():
                try:
                    parts.append(self.get_status_text(name, machine))
                except Exception as e:
                    parts.append(f"📊 *{name}*: ❌ unreachable ({e})")
            msg = "\n\n---\n\n".join(parts)
        else:
            name, machine = self.resolve_machine(target)
            if machine is None:
                available = ", ".join(self.machines.keys())
                await update.message.reply_text(
                    f"❌ Unknown machine `{target}`\nAvailable: `{available}`",
                    parse_mode="Markdown",
                )
                return
            try:
                msg = self.get_status_text(name, machine)
            except Exception as e:
                msg = f"📊 *{name}*: ❌ unreachable ({e})"

        if len(msg) > 4000:
            msg = msg[:4000] + "\n\n... (truncated)"

        try:
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(msg)

    async def cmd_concerns(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Get Stargazer concerns. Usage: /concerns [machine|all]"""
        if not self.is_authorized(update.effective_user.id):
            return

        target = ctx.args[0] if ctx.args else None

        if target == "all":
            parts = []
            for name, machine in self.machines.items():
                parts.append(self.get_concerns_text(name, machine))
            msg = "\n\n---\n\n".join(parts)
        else:
            name, machine = self.resolve_machine(target)
            if machine is None:
                available = ", ".join(self.machines.keys())
                await update.message.reply_text(
                    f"❌ Unknown machine `{target}`\nAvailable: `{available}`",
                    parse_mode="Markdown",
                )
                return
            msg = self.get_concerns_text(name, machine)

        if len(msg) > 4000:
            msg = msg[:4000] + "\n\n... (truncated)"

        try:
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(msg)

    async def cmd_order(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Send order. Usage: /order [machine] <message> or /order all <message>"""
        if not self.is_authorized(update.effective_user.id):
            return

        if not ctx.args:
            available = ", ".join(self.machines.keys())
            await update.message.reply_text(
                "Usage: `/order [machine] <message>`\n"
                f"Machines: `{available}`\n"
                "Example: `/order focus on tools/metrics/ changes`\n"
                "Example: `/order lab-server check test regressions`\n"
                "Example: `/order all pause until further notice`",
                parse_mode="Markdown",
            )
            return

        first_arg = ctx.args[0]
        if first_arg == "all":
            targets = list(self.machines.items())
            order_text = " ".join(ctx.args[1:])
        elif first_arg in self.machines:
            targets = [(first_arg, self.machines[first_arg])]
            order_text = " ".join(ctx.args[1:])
        else:
            targets = [(self.default_machine, self.machines[self.default_machine])]
            order_text = " ".join(ctx.args)

        if not order_text:
            await update.message.reply_text("❌ Order message cannot be empty.")
            return

        delivered = []
        for name, machine in targets:
            if self.is_local(machine):
                orders_dir = (
                    machine["repo_path"] / ".sisyphus" / "notepads" / "galaxy-orders"
                )
                orders_dir.mkdir(parents=True, exist_ok=True)

                order = {
                    "type": "galaxy_order",
                    "from": "galaxy-gazer",
                    "target": name,
                    "command": "general",
                    "payload": order_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "acknowledged": False,
                }

                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                order_file = orders_dir / f"{ts}.json"
                with open(order_file, "w") as f:
                    json.dump(order, f, indent=2)
                delivered.append(name)

                self.pending_orders[str(order_file)] = {
                    "machine": name,
                    "chat_id": update.effective_chat.id,
                    "order_text": order_text,
                }
            else:
                delivered.append(f"{name} (remote — pending SSH)")

        targets_str = ", ".join(delivered)
        await update.message.reply_text(
            f"📡 Order delivered to *{targets_str}*:\n> {order_text}",
            parse_mode="Markdown",
        )

    async def cmd_machines(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """List registered machines."""
        if not self.is_authorized(update.effective_user.id):
            return

        lines = ["🖥️ *Registered Machines*\n"]
        for name, machine in self.machines.items():
            host = machine["host"]
            local = "📍 local" if self.is_local(machine) else f"🌐 {host}"
            default = " _(default)_" if name == self.default_machine else ""
            lines.append(f"• `{name}` — {local}{default}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Show available commands."""
        if not self.is_authorized(update.effective_user.id):
            return

        available = ", ".join(self.machines.keys())
        await update.message.reply_text(
            "🌌 *Galaxy-gazer Commands*\n\n"
            "`/status [machine|all]` — Machine status (git, tests, reports)\n"
            "`/concerns [machine|all]` — Latest Stargazer concerns\n"
            "`/order [machine|all] <msg>` — Send order to Stargazer\n"
            "`/machines` — List registered machines\n"
            "`/help` — This message\n\n"
            f"📍 Machines: `{available}`\n"
            f"📍 Default: `{self.default_machine}`",
            parse_mode="Markdown",
        )

    # --- BACKGROUND POLLING ---

    async def poll_outbox_messages(self):
        """Background task: Check for proactive messages from agents."""
        while True:
            await asyncio.sleep(self.poll_interval / 2)

            for machine_name, machine_config in self.machines.items():
                if not self.is_local(machine_config):
                    continue

                repo = machine_config["repo_path"]
                outbox_dir = repo / ".sisyphus/notepads/galaxy-outbox"

                if not outbox_dir.exists():
                    continue

                outbox_files = sorted(glob.glob(str(outbox_dir / "*.json")))

                for outbox_file in outbox_files:
                    try:
                        with open(outbox_file) as f:
                            msg_data = json.load(f)

                        if msg_data.get("sent"):
                            continue

                        severity = msg_data.get("severity", "info")
                        from_agent = msg_data.get("from", machine_name)
                        message = msg_data.get("message", "")

                        emoji_map = {
                            "critical": "🚨",
                            "warning": "⚠️",
                            "info": "ℹ️",
                            "success": "✅",
                            "alert": "🔔",
                        }
                        emoji = emoji_map.get(severity, "📬")

                        order_payload = msg_data.get("order_payload", "")
                        if order_payload:
                            header = (
                                f"{emoji} <b>{from_agent}</b>\n"
                                f"\U0001f4e8 <i>{order_payload[:100]}</i>\n\n"
                            )
                        else:
                            header = f"{emoji} <b>{from_agent}</b>\n\n"

                        full_text = header + message
                        chunks = []
                        while full_text:
                            if len(full_text) <= 4000:
                                chunks.append(full_text)
                                break
                            split_at = full_text.rfind("\n", 0, 4000)
                            if split_at < 2000:
                                split_at = 4000
                            chunks.append(full_text[:split_at])
                            full_text = full_text[split_at:].lstrip("\n")

                        for user_id in self.authorized:
                            for chunk in chunks:
                                try:
                                    await self.app.bot.send_message(
                                        chat_id=user_id, text=chunk, parse_mode="HTML"
                                    )
                                except Exception:
                                    try:
                                        await self.app.bot.send_message(
                                            chat_id=user_id, text=chunk
                                        )
                                    except Exception as e:
                                        logger.error(f"[outbox] Failed to send to {user_id}: {e}")

                        msg_data["sent"] = True
                        msg_data["sent_at"] = datetime.now(timezone.utc).isoformat()
                        with open(outbox_file, "w") as f:
                            json.dump(msg_data, f, indent=2)

                        logger.info(f"[outbox] Sent message from {machine_name}/{from_agent}")

                    except Exception as e:
                        logger.error(f"[outbox] Error processing {outbox_file}: {e}")

    async def poll_order_acknowledgments(self):
        """Background task: Check for acknowledged orders and responses."""
        while True:
            await asyncio.sleep(self.poll_interval)

            completed = []
            for order_file, tracking in list(self.pending_orders.items()):
                order_path = Path(order_file)

                if not order_path.exists():
                    completed.append(order_file)
                    continue

                try:
                    with open(order_path) as f:
                        order_data = json.load(f)

                    if order_data.get("acknowledged"):
                        machine = tracking["machine"]
                        order_text = tracking["order_text"]
                        chat_id = tracking["chat_id"]

                        machine_config = self.machines.get(machine)
                        if machine_config and self.is_local(machine_config):
                            repo = machine_config["repo_path"]
                            order_ts = Path(order_file).stem
                            matching_response = (
                                repo / f".sisyphus/notepads/galaxy-order-response-{order_ts}.md"
                            )

                            response_file = None
                            if matching_response.exists():
                                response_file = str(matching_response)
                            else:
                                response_pattern = str(
                                    repo / ".sisyphus/notepads/galaxy-order-response-*.md"
                                )
                                responses = sorted(glob.glob(response_pattern))
                                if responses:
                                    response_file = responses[-1]

                            if response_file:
                                with open(response_file) as rf:
                                    response_text = rf.read()

                                lines = response_text.strip().split("\n")
                                summary_lines = []
                                for line in lines:
                                    if line.startswith("#"):
                                        continue
                                    if line.strip():
                                        summary_lines.append(line.strip())
                                    if len("\n".join(summary_lines)) > 300:
                                        break
                                    if line.strip() == "" and summary_lines:
                                        break

                                if len(response_text) <= 1000:
                                    header_msg = (
                                        f"✅ <b>Order Acknowledged</b>\n\n"
                                        f"📍 <code>{machine}</code>\n"
                                        f"📨 <i>{order_text}</i>"
                                    )
                                    compact_response = self.format_response_compact(
                                        response_text
                                    )

                                    await self.app.bot.send_message(
                                        chat_id=chat_id,
                                        text=header_msg,
                                        parse_mode="HTML",
                                    )
                                    await self.app.bot.send_message(
                                        chat_id=chat_id,
                                        text=compact_response,
                                        parse_mode="HTML",
                                    )
                                else:
                                    compact_summary = self.format_response_compact(
                                        response_text
                                    )[:400]
                                    msg = (
                                        f"✅ <b>Order Acknowledged</b>\n\n"
                                        f"📍 <code>{machine}</code>\n"
                                        f"📨 <i>{order_text}</i>\n\n"
                                        f"<b>Summary:</b>\n{compact_summary}...\n\n"
                                        f"📎 Full response attached"
                                    )
                                    await self.app.bot.send_message(
                                        chat_id=chat_id,
                                        text=msg,
                                        parse_mode="HTML",
                                    )
                                    with open(response_file, "rb") as f:
                                        await self.app.bot.send_document(
                                            chat_id=chat_id,
                                            document=f,
                                            filename=Path(response_file).name,
                                            caption=f"📄 Full response from {machine}",
                                        )
                            else:
                                no_response_msg = (
                                    f"✅ <b>Order Acknowledged</b>\n\n"
                                    f"📍 <code>{machine}</code>\n"
                                    f"📨 <i>{order_text}</i>\n\n"
                                    f"⏳ <i>No response notepad yet</i>"
                                )
                                await self.app.bot.send_message(
                                    chat_id=chat_id,
                                    text=no_response_msg,
                                    parse_mode="HTML",
                                )

                        completed.append(order_file)

                except Exception as e:
                    logger.error(f"[poll] Error checking {order_file}: {e}")

            for order_file in completed:
                self.pending_orders.pop(order_file, None)

    # --- BASECHANNEL INTERFACE ---

    async def _post_init(self, app):
        """Called after bot initialization - start background tasks."""
        asyncio.create_task(self.poll_order_acknowledgments())
        asyncio.create_task(self.poll_outbox_messages())

    async def start(self) -> None:
        """Start Telegram bot with polling."""
        if "CHANGE-ME" in self.token:
            raise ValueError(
                "Update telegram_token in config. See config.json.example"
            )

        self.app = ApplicationBuilder().token(self.token).post_init(self._post_init).build()

        self.app.add_handler(CommandHandler("start", self.cmd_help))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("concerns", self.cmd_concerns))
        self.app.add_handler(CommandHandler("order", self.cmd_order))
        self.app.add_handler(CommandHandler("machines", self.cmd_machines))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text)
        )

        machine_list = ", ".join(self.machines.keys())
        logger.info(f"🌌 TelegramChannel online — default: {self.default_machine}")
        logger.info(f"📞 Machines: {machine_list}")

        # run_polling blocks — use initialize + start + updater for non-blocking
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self) -> None:
        """Stop Telegram bot gracefully."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("TelegramChannel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send message to Telegram chat."""
        if not self.app:
            logger.warning("TelegramChannel not started, cannot send")
            return

        try:
            # Try HTML parse mode first (supports compact format)
            await self.app.bot.send_message(
                chat_id=int(msg.chat_id),
                text=msg.content,
                parse_mode="HTML",
            )
        except Exception:
            try:
                await self.app.bot.send_message(
                    chat_id=int(msg.chat_id),
                    text=msg.content,
                )
            except Exception as e:
                logger.error(f"Failed to send to {msg.chat_id}: {e}")
