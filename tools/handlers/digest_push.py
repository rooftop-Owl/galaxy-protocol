from datetime import datetime
from zoneinfo import ZoneInfo
import importlib
import sys
from pathlib import Path

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.telegram_utils import split_message


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
        timezone=ZoneInfo("Asia/Seoul"),
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
        chunks = split_message(message, max_length=4000)
        for chunk in chunks:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")


def format_digest_message(digest_data):
    schema_version = digest_data.get("schema_version", "1.0")

    if schema_version == "2.0":
        digest_data = _transform_v2_to_v1(digest_data)

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


def _transform_v2_to_v1(v2_data):
    patterns = _extract_patterns_from_diagnostic(v2_data)
    references = _extract_references_from_diagnostic(v2_data)
    actions = _extract_actions_from_diagnostic(v2_data)

    return {
        "patterns": patterns,
        "references": references,
        "actions": actions,
    }


def _extract_patterns_from_diagnostic(diagnostic):
    patterns = []

    for opp in diagnostic.get("opportunities", []):
        if isinstance(opp, dict):
            if "architecture" in opp:
                patterns.append({"name": opp["architecture"]})
            elif "pattern" in opp:
                patterns.append({"name": opp["pattern"]})

    for trend in diagnostic.get("trends", []):
        if isinstance(trend, dict) and "description" in trend:
            patterns.append({"name": trend["description"]})
        elif isinstance(trend, str):
            patterns.append({"name": trend})

    return patterns


def _extract_references_from_diagnostic(diagnostic):
    refs = diagnostic.get("references", [])

    if isinstance(refs, list):
        return [{"title": ref} if isinstance(ref, str) else ref for ref in refs]

    return []


def _extract_actions_from_diagnostic(diagnostic):
    actions = []

    for opp in diagnostic.get("opportunities", []):
        if isinstance(opp, dict) and "adoption_path" in opp:
            actions.append({"description": opp["adoption_path"]})

    for item in diagnostic.get("watch_list", []):
        if isinstance(item, dict) and "action" in item:
            actions.append({"description": item["action"]})
        elif isinstance(item, str):
            actions.append({"description": f"Watch: {item}"})

    return actions
