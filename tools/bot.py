#!/usr/bin/env python3
"""
Galaxy Telegram Bot — Bidirectional relay

Any text message = order for the default machine.
Slash commands for introspection (/status, /concerns, /machines).

Setup:
  1. Create bot via @BotFather on Telegram, get token
  2. Message @userinfobot to get your Telegram user ID
  3. Copy tools/galaxy/config.json.example to .galaxy/config.json
  4. Fill in telegram_token, authorized_users, machines
  5. Install: pip install -r tools/galaxy/requirements.txt
  6. Test: python3 tools/galaxy/bot.py
  7. Deploy: sudo cp tools/galaxy/galaxy.service /etc/systemd/system/
             sudo systemctl enable --now galaxy

See: .sisyphus/drafts/galaxy-gazer-protocol/phase2-telegram.md
"""

import json
import glob
import shlex
import subprocess
import sys
import asyncio
import re
import importlib
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)


# --- CONFIG ---

CONFIG_PATH = Path(__file__).parent.parent.parent / ".galaxy" / "config.json"

try:
    with open(CONFIG_PATH) as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print(f"Error: Config not found at {CONFIG_PATH}")
    print("Copy tools/galaxy/config.json.example to .galaxy/config.json")
    sys.exit(1)

TOKEN = CONFIG["telegram_token"]
AUTHORIZED = set(CONFIG["authorized_users"])
digest_scheduler = None


def _load_module(name):
    return importlib.import_module(name)


common = _load_module("handlers.common")
feed_handler = _load_module("handlers.feed_handler")
voice_handler = _load_module("handlers.voice_handler")
document_handler = _load_module("handlers.document_handler")
router = _load_module("handlers.router")
priority_handler = _load_module("handlers.priority_handler")
digest_push = _load_module("handlers.digest_push")


# --- MACHINE REGISTRY ---


def load_machines(config):
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
                config.get("repo_path", str(Path(__file__).parent.parent.parent))
            ),
            "machine_name": name,
        }
    }


MACHINES = load_machines(CONFIG)
DEFAULT_MACHINE = CONFIG.get("default_machine", next(iter(MACHINES)))
POLL_INTERVAL = CONFIG.get("poll_interval", 30)  # seconds

# Track pending orders for acknowledgment polling
# Format: { order_file_path: { "machine": name, "chat_id": id, "message_id": id } }
pending_orders = {}


def is_authorized(user_id: int) -> bool:
    return user_id in AUTHORIZED


def format_response_compact(text):
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
    # Collapse multiple newlines to max 2
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result[:1500]  # Hard cap for sanity


def resolve_machine(name):
    """Resolve a machine name. Returns (machine_name, machine_config) or (None, None)."""
    if name is None:
        return DEFAULT_MACHINE, MACHINES[DEFAULT_MACHINE]
    if name in MACHINES:
        return name, MACHINES[name]
    return None, None


def is_local(machine):
    """Check if a machine config points to localhost."""
    return machine["host"] in ("localhost", "127.0.0.1", "")


def run_on_machine(machine, cmd):
    """Run a command on a machine. Local = subprocess, remote = ssh.

    Returns (stdout, stderr, returncode).
    """
    repo = str(machine["repo_path"])

    if is_local(machine):
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=repo, timeout=30
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode

    # Remote: SSH
    host = machine["host"]
    ssh_user = machine.get("ssh_user", "")
    target = f"{ssh_user}@{host}" if ssh_user else host
    ssh_cmd = [
        "ssh",
        "-o",
        "ConnectTimeout=5",
        target,
        f"cd {shlex.quote(str(repo))} && {' '.join(shlex.quote(c) for c in cmd)}",
    ]

    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


# --- COMMAND HELPERS ---


def get_status_text(name, machine):
    """Build status text for a single machine."""
    try:
        git_log, _, _ = run_on_machine(machine, ["git", "log", "--oneline", "-5"])
    except Exception:
        git_log = "(git unavailable)"

    try:
        git_status, _, _ = run_on_machine(machine, ["git", "status", "--short"])
        git_status = git_status or "(clean)"
    except Exception:
        git_status = "(unknown)"

    try:
        stdout, _, _ = run_on_machine(
            machine, ["python3", "-m", "pytest", "tests/", "-q", "--tb=no"]
        )
        test_line = stdout.split("\n")[-1] if stdout else "unknown"
    except Exception:
        test_line = "(pytest unavailable)"

    # Stargazer reports (local only — can't glob over SSH)
    report_summary = "No reports"
    if is_local(machine):
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


def get_concerns_text(name, machine):
    """Get concerns text for a single machine (local only)."""
    if not is_local(machine):
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


def create_order(machine_name, machine_config, order_text, chat_id):
    """Write an order JSON file. Returns the order file path or None."""
    if not is_local(machine_config):
        return None

    orders_dir = (
        machine_config["repo_path"] / ".sisyphus" / "notepads" / "galaxy-orders"
    )
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


def create_enhanced_order(
    machine_name, machine_config, order_text, chat_id, metadata=None
):
    if not is_local(machine_config):
        return None
    orders_dir = (
        machine_config["repo_path"] / ".sisyphus" / "notepads" / "galaxy-orders"
    )
    order = common.build_order(machine_name, order_text, metadata=metadata)
    order_file = common.write_order(orders_dir, order, message_id=chat_id)
    return str(order_file)


def _build_order_metadata(order_text, project_name):
    temp_order = common.build_order(
        DEFAULT_MACHINE, order_text, {"project": project_name}
    )
    clean_text, temp_order = priority_handler.apply_priority_and_schedule(
        order_text, temp_order
    )
    try:
        priority_handler.validate_order(temp_order)
    except Exception:
        temp_order = common.build_order(
            DEFAULT_MACHINE, clean_text, {"project": project_name}
        )
    return clean_text, {
        "priority": temp_order.get("priority", "normal"),
        "project": temp_order.get("project", project_name),
        "media": temp_order.get("media", None),
        "scheduled_for": temp_order.get("scheduled_for"),
    }


async def _submit_text_order_from_media(update: Update, order_text: str):
    if update.message is None or update.effective_chat is None:
        return
    name = DEFAULT_MACHINE
    machine = MACHINES[name]
    project_name, routed_text = router.route_text(order_text, CONFIG)
    clean_text, order_meta = _build_order_metadata(routed_text, project_name)
    order_file = create_enhanced_order(
        name,
        machine,
        clean_text,
        update.effective_chat.id,
        metadata=order_meta,
    )
    if order_file:
        pending_orders[order_file] = {
            "machine": name,
            "chat_id": update.effective_chat.id,
            "order_text": clean_text,
        }
        await update.message.reply_text(
            f"\U0001f4e1 \u2192 *{name}*", parse_mode="Markdown"
        )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Any plain text message = order for default machine."""
    if (
        update.effective_user is None
        or update.message is None
        or update.effective_chat is None
    ):
        return
    if not is_authorized(update.effective_user.id):
        return

    order_text = (update.message.text or "").strip()
    if not order_text:
        return

    name = DEFAULT_MACHINE
    machine = MACHINES[name]

    handled = await feed_handler.maybe_handle_github_reference(
        update, ctx, CONFIG, machine
    )
    if handled:
        return

    project_name, routed_text = router.route_text(order_text, CONFIG)
    clean_text, order_meta = _build_order_metadata(routed_text, project_name)
    order_file = create_enhanced_order(
        name,
        machine,
        clean_text,
        update.effective_chat.id,
        metadata=order_meta,
    )

    if order_file:
        pending_orders[order_file] = {
            "machine": name,
            "chat_id": update.effective_chat.id,
            "order_text": clean_text,
        }
        await update.message.reply_text(
            f"\U0001f4e1 \u2192 *{name}*", parse_mode="Markdown"
        )


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    if not is_authorized(update.effective_user.id):
        return
    await voice_handler.handle_voice(
        update,
        ctx,
        CONFIG,
        lambda text: _submit_text_order_from_media(update, text),
    )


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    if not is_authorized(update.effective_user.id):
        return
    machine = MACHINES[DEFAULT_MACHINE]
    await document_handler.handle_photo(update, ctx, CONFIG, machine)


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    if not is_authorized(update.effective_user.id):
        return
    machine = MACHINES[DEFAULT_MACHINE]
    await document_handler.handle_pdf(update, ctx, CONFIG, machine)


# --- COMMANDS ---


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Get machine status. Usage: /status [machine|all]"""
    if update.effective_user is None or update.message is None:
        return
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"❌ Unauthorized\n"
            f"Your Telegram user ID: `{user_id}`\n\n"
            f"Add this to `.galaxy/config.json`:\n"
            f'`"authorized_users": [{user_id}]`',
            parse_mode="Markdown",
        )
        return

    target = ctx.args[0] if ctx.args else None

    if target == "all":
        parts = []
        for name, machine in MACHINES.items():
            try:
                parts.append(get_status_text(name, machine))
            except Exception as e:
                parts.append(f"📊 *{name}*: ❌ unreachable ({e})")
        msg = "\n\n---\n\n".join(parts)
    else:
        name, machine = resolve_machine(target)
        if machine is None:
            available = ", ".join(MACHINES.keys())
            await update.message.reply_text(
                f"❌ Unknown machine `{target}`\nAvailable: `{available}`",
                parse_mode="Markdown",
            )
            return
        try:
            msg = get_status_text(name, machine)
        except Exception as e:
            msg = f"📊 *{name}*: ❌ unreachable ({e})"

    # Truncate if needed (all mode can get long)
    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n... (truncated)"

    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(msg)


async def cmd_concerns(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Get Stargazer concerns. Usage: /concerns [machine|all]"""
    if update.effective_user is None or update.message is None:
        return
    if not is_authorized(update.effective_user.id):
        return

    target = ctx.args[0] if ctx.args else None

    if target == "all":
        parts = []
        for name, machine in MACHINES.items():
            parts.append(get_concerns_text(name, machine))
        msg = "\n\n---\n\n".join(parts)
    else:
        name, machine = resolve_machine(target)
        if machine is None:
            available = ", ".join(MACHINES.keys())
            await update.message.reply_text(
                f"❌ Unknown machine `{target}`\nAvailable: `{available}`",
                parse_mode="Markdown",
            )
            return
        msg = get_concerns_text(name, machine)

    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n... (truncated)"

    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(msg)


async def cmd_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send order. Usage: /order [machine] <message> or /order all <message>"""
    if (
        update.effective_user is None
        or update.message is None
        or update.effective_chat is None
    ):
        return
    if not is_authorized(update.effective_user.id):
        return

    if not ctx.args:
        available = ", ".join(MACHINES.keys())
        await update.message.reply_text(
            "Usage: `/order [machine] <message>`\n"
            f"Machines: `{available}`\n"
            "Example: `/order focus on tools/metrics/ changes`\n"
            "Example: `/order lab-server check test regressions`\n"
            "Example: `/order all pause until further notice`",
            parse_mode="Markdown",
        )
        return

    # Check if first arg is a machine name or "all"
    first_arg = ctx.args[0]
    if first_arg == "all":
        targets = list(MACHINES.items())
        order_text = " ".join(ctx.args[1:])
    elif first_arg in MACHINES:
        targets = [(first_arg, MACHINES[first_arg])]
        order_text = " ".join(ctx.args[1:])
    else:
        # No machine specified — use default, all args are the message
        targets = [(DEFAULT_MACHINE, MACHINES[DEFAULT_MACHINE])]
        order_text = " ".join(ctx.args)

    if not order_text:
        await update.message.reply_text("❌ Order message cannot be empty.")
        return

    delivered = []
    for name, machine in targets:
        if is_local(machine):
            project_name, routed_text = router.route_text(order_text, CONFIG)
            clean_text, order_meta = _build_order_metadata(routed_text, project_name)
            order_file = create_enhanced_order(
                name,
                machine,
                clean_text,
                update.effective_chat.id,
                metadata=order_meta,
            )
            delivered.append(name)

            # Track for acknowledgment polling
            pending_orders[order_file] = {
                "machine": name,
                "chat_id": update.effective_chat.id,
                "order_text": clean_text,
            }
        else:
            # Remote: SSH write (future — for now, note it)
            delivered.append(f"{name} (remote — pending SSH)")

    targets_str = ", ".join(delivered)
    await update.message.reply_text(
        f"📡 Order delivered to *{targets_str}*:\n> {order_text}", parse_mode="Markdown"
    )


async def cmd_machines(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """List registered machines."""
    if update.effective_user is None or update.message is None:
        return
    if not is_authorized(update.effective_user.id):
        return

    lines = ["🖥️ *Registered Machines*\n"]
    for name, machine in MACHINES.items():
        host = machine["host"]
        local = "📍 local" if is_local(machine) else f"🌐 {host}"
        default = " _(default)_" if name == DEFAULT_MACHINE else ""
        lines.append(f"• `{name}` — {local}{default}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show available commands."""
    if update.effective_user is None or update.message is None:
        return
    if not is_authorized(update.effective_user.id):
        return

    available = ", ".join(MACHINES.keys())
    await update.message.reply_text(
        "🌌 *Galaxy-gazer Commands*\n\n"
        "`/status [machine|all]` — Machine status (git, tests, reports)\n"
        "`/concerns [machine|all]` — Latest Stargazer concerns\n"
        "`/order [machine|all] <msg>` — Send order to Stargazer\n"
        "`/machines` — List registered machines\n"
        "`/help` — This message\n\n"
        f"📍 Machines: `{available}`\n"
        f"📍 Default: `{DEFAULT_MACHINE}`",
        parse_mode="Markdown",
    )


# --- ORDER POLLING ---


async def poll_outbox_messages(app):
    """Background task: Check for proactive messages from agents.

    Outbox Message Schema:
    {
        "type": "notification",           // Message type (currently only "notification")
        "severity": "success",             // One of: critical, warning, info, success, alert
        "from": "Agent Name",              // Agent or system name sending the message
        "message": "HTML formatted text", // Message body (supports <b>, <i>, <code> tags)
        "timestamp": "2026-02-02T03:45:00.000Z",  // ISO 8601 timestamp
        "sent": false,                     // Tracking field (bot sets to true after sending)
        "sent_at": "2026-02-02T03:51:22.517305+00:00"  // Added by bot after sending
    }

    Location: .sisyphus/notepads/galaxy-outbox/*.json
    Polling interval: POLL_INTERVAL / 2 (default: 30s)

    Severity emoji mapping:
    - critical: 🚨
    - warning: ⚠️
    - info: ℹ️
    - success: ✅
    - alert: 🔔
    """
    while True:
        await asyncio.sleep(POLL_INTERVAL / 2)  # Poll outbox more frequently (30s)

        for machine_name, machine_config in MACHINES.items():
            if not is_local(machine_config):
                continue  # Skip remote machines for now

            repo = Path(machine_config["repo_path"])
            outbox_dir = repo / ".sisyphus/notepads/galaxy-outbox"

            if not outbox_dir.exists():
                continue

            # Find unsent messages
            outbox_files = sorted(glob.glob(str(outbox_dir / "*.json")))

            for outbox_file in outbox_files:
                try:
                    with open(outbox_file) as f:
                        msg_data = json.load(f)

                    # Skip if already sent
                    if msg_data.get("sent"):
                        continue

                    # Extract message details
                    severity = msg_data.get("severity", "info")
                    from_agent = msg_data.get("from", machine_name)
                    message = msg_data.get("message", "")
                    msg_type = msg_data.get("type", "notification")

                    # Choose emoji based on severity
                    emoji_map = {
                        "critical": "🚨",
                        "warning": "⚠️",
                        "info": "ℹ️",
                        "success": "✅",
                        "alert": "🔔",
                    }
                    emoji = emoji_map.get(severity, "📬")

                    # Build message with order context
                    order_payload = msg_data.get("order_payload", "")
                    if order_payload:
                        header = (
                            f"{emoji} <b>{from_agent}</b>\n"
                            f"\U0001f4e8 <i>{order_payload[:100]}</i>\n\n"
                        )
                    else:
                        header = f"{emoji} <b>{from_agent}</b>\n\n"

                    # Split into chunks for Telegram (4096 char limit)
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

                    for user_id in AUTHORIZED:
                        for chunk in chunks:
                            try:
                                await app.bot.send_message(
                                    chat_id=user_id, text=chunk, parse_mode="HTML"
                                )
                            except Exception:
                                try:
                                    await app.bot.send_message(
                                        chat_id=user_id, text=chunk
                                    )
                                except Exception as e:
                                    print(f"[outbox] Failed to send to {user_id}: {e}")

                    # Mark as sent
                    msg_data["sent"] = True
                    msg_data["sent_at"] = datetime.now(timezone.utc).isoformat()
                    with open(outbox_file, "w") as f:
                        json.dump(msg_data, f, indent=2)

                    print(f"[outbox] Sent message from {machine_name}/{from_agent}")

                except Exception as e:
                    print(f"[outbox] Error processing {outbox_file}: {e}")


async def poll_order_acknowledgments(app):
    """Background task: Check for acknowledged orders and responses."""
    while True:
        await asyncio.sleep(POLL_INTERVAL)

        completed = []
        for order_file, tracking in list(pending_orders.items()):
            order_path = Path(order_file)

            # Check if order file still exists
            if not order_path.exists():
                completed.append(order_file)
                continue

            try:
                with open(order_path) as f:
                    order_data = json.load(f)

                # Check if acknowledged
                if order_data.get("acknowledged"):
                    machine = tracking["machine"]
                    order_text = tracking["order_text"]
                    chat_id = tracking["chat_id"]

                    # Look for response notepad matching this order
                    machine_config = MACHINES.get(machine)
                    if machine_config and is_local(machine_config):
                        repo = Path(machine_config["repo_path"])
                        order_ts = Path(order_file).stem
                        matching_response = (
                            repo
                            / f".sisyphus/notepads/galaxy-order-response-{order_ts}.md"
                        )

                        # Fall back to latest response if exact match not found
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

                            # Extract summary (first paragraph or first 300 chars)
                            lines = response_text.strip().split("\n")
                            summary_lines = []
                            for line in lines:
                                if line.startswith("#"):  # Skip headers
                                    continue
                                if line.strip():
                                    summary_lines.append(line.strip())
                                if len("\n".join(summary_lines)) > 300:
                                    break
                                if line.strip() == "" and summary_lines:
                                    break  # End of first paragraph

                            summary = "\n".join(summary_lines[:3])  # Max 3 lines
                            if len(summary) > 300:
                                summary = summary[:300] + "..."

                            # Decision: Short inline, long as attachment
                            if len(response_text) <= 1000:
                                # Short response: compact emoji format
                                header_msg = (
                                    f"✅ <b>Order Acknowledged</b>\n\n"
                                    f"📍 <code>{machine}</code>\n"
                                    f"📨 <i>{order_text}</i>"
                                )
                                compact_response = format_response_compact(
                                    response_text
                                )

                                await app.bot.send_message(
                                    chat_id=chat_id, text=header_msg, parse_mode="HTML"
                                )
                                await app.bot.send_message(
                                    chat_id=chat_id,
                                    text=compact_response,
                                    parse_mode="HTML",
                                )
                            else:
                                # Long response: compact summary + file attachment
                                compact_summary = format_response_compact(
                                    response_text
                                )[:400]
                                msg = (
                                    f"✅ <b>Order Acknowledged</b>\n\n"
                                    f"📍 <code>{machine}</code>\n"
                                    f"📨 <i>{order_text}</i>\n\n"
                                    f"<b>Summary:</b>\n{compact_summary}...\n\n"
                                    f"📎 Full response attached"
                                )
                                await app.bot.send_message(
                                    chat_id=chat_id, text=msg, parse_mode="HTML"
                                )
                                # Send file attachment
                                with open(response_file, "rb") as f:
                                    await app.bot.send_document(
                                        chat_id=chat_id,
                                        document=f,
                                        filename=Path(response_file).name,
                                        caption=f"📄 Full response from {machine}",
                                    )
                        else:
                            # No response found
                            no_response_msg = (
                                f"✅ <b>Order Acknowledged</b>\n\n"
                                f"📍 <code>{machine}</code>\n"
                                f"📨 <i>{order_text}</i>\n\n"
                                f"⏳ <i>No response notepad yet</i>"
                            )
                            await app.bot.send_message(
                                chat_id=chat_id, text=no_response_msg, parse_mode="HTML"
                            )

                    completed.append(order_file)

            except Exception as e:
                print(f"[poll] Error checking {order_file}: {e}")

        # Clean up completed orders
        for order_file in completed:
            pending_orders.pop(order_file, None)


# --- MAIN ---


async def post_init(app):
    """Called after bot initialization - start background tasks."""
    asyncio.create_task(poll_order_acknowledgments(app))
    asyncio.create_task(poll_outbox_messages(app))
    global digest_scheduler
    digest_scheduler = digest_push.setup_digest_scheduler(
        CONFIG, app.bot, _load_latest_digest
    )


def _load_latest_digest():
    return {"patterns": [], "references": [], "actions": []}


def main():
    if "CHANGE-ME" in TOKEN:
        print("Error: Update telegram_token in .galaxy/config.json")
        print("See: tools/galaxy/config.json.example")
        return 1

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("concerns", cmd_concerns))
    app.add_handler(CommandHandler("order", cmd_order))
    app.add_handler(CommandHandler("machines", cmd_machines))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    machine_list = ", ".join(MACHINES.keys())
    print(f"\U0001f30c Galaxy bot online \u2014 default: {DEFAULT_MACHINE}")
    print(f"\U0001f4de Any text message = order")

    app.run_polling()


if __name__ == "__main__":
    sys.exit(main() or 0)
