from datetime import datetime
import importlib


def setup_digest_scheduler(config, bot, digest_loader):
    if not config.get("features", {}).get("GALAXY_DIGEST_PUSH_ENABLED", False):
        return None

    sqlalchemy_jobstore = importlib.import_module("apscheduler.jobstores.sqlalchemy")
    asyncio_scheduler = importlib.import_module("apscheduler.schedulers.asyncio")

    db_path = config.get("digest_push", {}).get("persistence_db", ".galaxy/jobs.sqlite")
    jobstores = {
        "default": sqlalchemy_jobstore.SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    }
    scheduler = asyncio_scheduler.AsyncIOScheduler(jobstores=jobstores)
    scheduler.add_job(
        send_daily_digest,
        "cron",
        hour=int(config.get("digest_push", {}).get("hour", 9)),
        minute=int(config.get("digest_push", {}).get("minute", 0)),
        args=[bot, config, digest_loader],
        id="galaxy-daily-digest",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


async def send_daily_digest(bot, config, digest_loader):
    digest_data = digest_loader()
    message = format_digest_message(digest_data)
    subscribers = config.get("digest_push", {}).get("digest_subscribers", [])
    for chat_id in subscribers:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")


def format_digest_message(digest_data):
    patterns = digest_data.get("patterns", [])
    references = digest_data.get("references", [])
    actions = digest_data.get("actions", [])

    lines = [f"📊 *Daily Digest* ({datetime.now().strftime('%Y-%m-%d')})", ""]
    if patterns:
        lines.append(f"🔍 *New Patterns* ({len(patterns)}):")
        lines.extend(f"- {item.get('name', item)}" for item in patterns[:3])
        lines.append("")
    if references:
        lines.append(f"📚 *New References* ({len(references)}):")
        lines.extend(f"- {item.get('title', item)}" for item in references[:5])
        lines.append("")
    if actions:
        lines.append(f"💡 *Action Items* ({len(actions)}):")
        lines.extend(f"- {item.get('description', item)}" for item in actions[:3])
        lines.append("")

    lines.append("👉 /digest for full details")
    return "\n".join(lines)
