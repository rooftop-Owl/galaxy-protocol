import asyncio
import json
import logging
import os
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import importlib
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
split_message = importlib.import_module("utils.telegram_utils").split_message

logger = logging.getLogger(__name__)

MIN_REFS_FOR_AUTO_DIGEST = 3
DIGEST_CREATION_TIMEOUT_SEC = 300


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _load_references_index() -> dict[str, Any]:
    data = _load_json(Path(".sisyphus/references/index.json"))
    if not isinstance(data, dict):
        return {"references": [], "digests": []}
    data.setdefault("references", [])
    data.setdefault("digests", [])
    return data


def _get_last_digest_date() -> str | None:
    index_path = Path(".sisyphus/digests/index.json")
    data = _load_json(index_path)
    if not isinstance(data, dict):
        return None

    digests = data.get("digests", [])
    if not isinstance(digests, list) or not digests:
        return None

    try:
        latest = sorted(digests, key=lambda d: d.get("date", ""), reverse=True)[0]
        return latest.get("date")
    except Exception:
        return None


def _get_new_refs(since_date: str | None) -> list[dict[str, Any]]:
    data = _load_references_index()
    refs = data.get("references", [])
    if not isinstance(refs, list):
        return []

    if since_date is None:
        return sorted(refs, key=lambda ref: ref.get("shared_at", ""))

    cutoff = since_date + "T23:59:59Z"
    new_refs = [ref for ref in refs if isinstance(ref, dict) and ref.get("shared_at", "") > cutoff]
    return sorted(new_refs, key=lambda ref: ref.get("shared_at", ""))


def _count_new_refs(since_date: str | None) -> int:
    return len(_get_new_refs(since_date))


def _slug_from_reference(ref: dict[str, Any]) -> str:
    file_name = str(ref.get("file", "")).strip()
    if file_name:
        return Path(file_name).stem

    slug = str(ref.get("slug", "")).strip()
    if slug:
        return slug

    return str(ref.get("title", "untitled")).strip() or "untitled"


def _load_hermes_session_id() -> str | None:
    data = _load_json(Path(".galaxy/hermes-session.json"))
    if not isinstance(data, dict):
        return None

    sid = data.get("session_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None


def _save_hermes_session_id(session_id: str) -> None:
    path = Path(".galaxy/hermes-session.json")
    payload = {
        "session_id": session_id,
        "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
    }
    _write_json_atomic(path, payload)


def _extract_session_id_from_events(stdout: bytes | None) -> str | None:
    if not stdout:
        return None

    try:
        text = stdout.decode("utf-8", errors="ignore")
    except Exception:
        return None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        sid = event.get("sessionID")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()

    return None


def _did_digest_advance(previous_date: str | None) -> bool:
    latest = _get_last_digest_date()
    if latest is None:
        return False
    if previous_date is None:
        return True
    return latest > previous_date


def _build_fallback_digest_payload(
    new_refs: list[dict[str, Any]],
    last_date: str | None,
) -> dict[str, Any]:
    tags = Counter()
    for ref in new_refs:
        raw_tags = ref.get("tags", [])
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, str) and tag.strip():
                    tags[tag.strip()] += 1

    pattern_names = [f"Tag signal: {tag}" for tag, _ in tags.most_common(3)]
    if not pattern_names:
        pattern_names = ["Reference intake trend"]

    patterns = [{"name": name} for name in pattern_names]
    references = [{"title": str(ref.get("title", _slug_from_reference(ref)))} for ref in new_refs]

    if last_date:
        action_desc = f"Auto-digest fallback used; summarize refs captured since {last_date}."
    else:
        action_desc = "Auto-digest fallback used; summarize full reference backlog."

    return {
        "digest_date": _today_kst(),
        "patterns": patterns,
        "references": references,
        "actions": [{"description": action_desc}],
    }


def _create_fallback_digest(
    last_digest_date: str | None,
    new_refs: list[dict[str, Any]],
) -> bool:
    if not new_refs:
        return False

    today = _today_kst()
    digest_dir = Path(".sisyphus/digests")
    digest_dir.mkdir(parents=True, exist_ok=True)

    digest_filename = f"digest-{today}-auto.md"
    digest_path = digest_dir / digest_filename

    refs_slugs: list[str] = []
    references_rows: list[tuple[str, str, str]] = []
    tag_counter = Counter()
    type_counter = Counter()

    for ref in new_refs:
        slug = _slug_from_reference(ref)
        title = str(ref.get("title", slug)).strip() or slug
        ref_type = str(ref.get("type", "unknown")).strip() or "unknown"

        refs_slugs.append(slug)
        references_rows.append((slug, title, ref_type))
        type_counter[ref_type] += 1

        raw_tags = ref.get("tags", [])
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, str) and tag.strip():
                    tag_counter[tag.strip()] += 1

    top_tags = tag_counter.most_common(3)
    top_types = type_counter.most_common(3)

    from_label = last_digest_date or "start"
    lines: list[str] = [
        f"# Digest: {today}-auto",
        "",
        f"**Generated**: {today}",
        f"**References processed**: {len(references_rows)}",
        f"**Date range**: {from_label} to {today}",
        "",
        "---",
        "",
        "## 1. Themes Observed",
        "",
        f"**Daily Reference Intake** — {len(references_rows)} new references captured since {from_label}.",
    ]

    if top_tags:
        tag_text = ", ".join(f"{tag} ({count})" for tag, count in top_tags)
        lines.append(f"**Tag Signals** — Top tags this cycle: {tag_text}.")
    else:
        lines.append("**Tag Signals** — No stable tag cluster detected in this cycle.")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Pattern Catalog",
            "",
            "| Pattern | Description | References | Context |",
            "|---------|-------------|------------|---------|",
            "| **Daily Intake Sweep** | Capture and summarize newly ingested references in one pass. | auto-fallback | Galaxy digest push scheduler |",
        ]
    )

    for ref_type, count in top_types:
        lines.append(
            f"| **Type Cluster: {ref_type}** | {count} references of type `{ref_type}` were captured in this window. | references-index | Daily ecosystem ingestion |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Anti-Patterns Observed",
            "",
            "| Anti-Pattern | Description | References | Count |",
            "|-------------|-------------|------------|-------|",
            "| **Stale Digest Push Summary** | Telegram push can become stale if digest auto-create does not produce a fresh digest artifact. | auto-fallback | 1 |",
            "",
            "---",
            "",
            "## 4. Architecture Notes",
            "",
            "This digest was generated by the scheduler fallback path because interactive `/digest` execution was unavailable in non-interactive mode. It preserves continuity by writing a valid digest artifact and updating digest tracking metadata.",
            "",
            "---",
            "",
            "## 5. When These Patterns Might Be Useful",
            "",
            "- When scheduled digest push runs while command-mode `/digest` execution is unavailable.",
            "- When you still need a dated digest artifact for daily continuity and recall indexing.",
            "",
            "---",
            "",
            "## 6. References Processed",
            "",
            "| Slug | Title | Type |",
            "|------|-------|------|",
        ]
    )

    for slug, title, ref_type in references_rows:
        lines.append(f"| `{slug}` | {title} | {ref_type} |")

    lines.extend(
        [
            "",
            f"<!-- refs_slugs: {json.dumps(refs_slugs, ensure_ascii=True)} -->",
            "",
        ]
    )

    digest_path.write_text("\n".join(lines), encoding="utf-8")

    refs_index_path = Path(".sisyphus/references/index.json")
    refs_index = _load_references_index()
    digests = refs_index.get("digests", [])
    if not isinstance(digests, list):
        digests = []

    digest_rel_path = f".sisyphus/digests/{digest_filename}"
    digests = [d for d in digests if isinstance(d, dict) and d.get("digest_file") != digest_rel_path]
    digests.append(
        {
            "date": today,
            "refs_processed": len(refs_slugs),
            "refs_slugs": refs_slugs,
            "digest_file": digest_rel_path,
        }
    )
    digests.sort(key=lambda d: (d.get("date", ""), d.get("digest_file", "")))

    refs_index["digests"] = digests
    refs_index["updated_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
    _write_json_atomic(refs_index_path, refs_index)

    result = subprocess.run(
        [sys.executable, "tools/digest_indexer.py"],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        logger.warning(
            "[digest] Fallback digest created, but index regeneration failed: %s",
            (result.stderr or "").strip()[:400],
        )
        return False

    logger.info("[digest] Fallback digest created: %s", digest_filename)
    return True


async def _run_opencode_command(command: list[str], env: dict[str, str]) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(Path.cwd()),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=DIGEST_CREATION_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, b"", b"timeout"

    return_code = process.returncode if process.returncode is not None else 1
    return return_code, stdout or b"", stderr or b""


async def _attempt_agent_digest_creation(previous_date: str | None) -> bool:
    opencode_runtime = importlib.import_module("opencode_runtime")
    opencode_binary, error = opencode_runtime.resolve_opencode_binary()
    if not opencode_binary:
        logger.warning("[digest] Auto-create skipped: opencode not found: %s", error)
        return False

    session_id = _load_hermes_session_id()
    commands: list[list[str]] = []
    if session_id:
        commands.append([opencode_binary, "run", "--format", "json", "--session", session_id, "/digest"])
        commands.append([opencode_binary, "run", "--format", "json", "--session", session_id, "--command", "digest"])

    commands.append([opencode_binary, "run", "--format", "json", "/digest"])
    commands.append([opencode_binary, "run", "--format", "json", "--command", "digest"])

    env = os.environ.copy()

    for command in commands:
        cmd_text = " ".join(command)
        return_code, stdout, stderr = await _run_opencode_command(command, env)

        sid = _extract_session_id_from_events(stdout)
        if sid:
            _save_hermes_session_id(sid)

        if _did_digest_advance(previous_date):
            logger.info("[digest] Auto-create completed via command: %s", cmd_text)
            return True

        stderr_text = stderr.decode("utf-8", errors="ignore").strip()
        logger.warning(
            "[digest] Auto-create command did not produce a fresh digest (exit=%s): %s | stderr=%s",
            return_code,
            cmd_text,
            stderr_text[:300],
        )

    return False


async def _spawn_digest_creation(last_digest_date: str | None, new_refs: list[dict[str, Any]]) -> bool:
    if await _attempt_agent_digest_creation(last_digest_date):
        return True

    logger.warning("[digest] Falling back to local digest generation")
    return _create_fallback_digest(last_digest_date, new_refs)


def setup_digest_scheduler(config, bot, digest_loader):
    if not config.get("features", {}).get("GALAXY_DIGEST_PUSH_ENABLED", False):
        return None

    asyncio_scheduler = importlib.import_module("apscheduler.schedulers.asyncio")

    scheduler = asyncio_scheduler.AsyncIOScheduler()
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


def _is_stub_reference_summary(digest_data: dict[str, Any]) -> bool:
    references = digest_data.get("references", [])
    if not isinstance(references, list) or len(references) != 1:
        return False

    item = references[0]
    if isinstance(item, dict):
        title = str(item.get("title", ""))
    else:
        title = str(item)

    return "references processed" in title.lower()


async def send_daily_digest(bot, config, digest_loader):
    min_refs = config.get("digest_push", {}).get("min_refs_for_auto_digest", MIN_REFS_FOR_AUTO_DIGEST)
    last_date = _get_last_digest_date()
    new_refs = _get_new_refs(last_date)
    new_count = len(new_refs)

    created = False
    if new_count >= min_refs:
        logger.info("[digest] %s new refs since %s — auto-creating digest", new_count, last_date)
        created = await _spawn_digest_creation(last_date, new_refs)
    else:
        logger.info("[digest] %s new refs (threshold %s) — skipping auto-create", new_count, min_refs)

    digest_data = digest_loader()
    if not isinstance(digest_data, dict):
        digest_data = {"patterns": [], "references": [], "actions": []}

    digest_date = digest_data.get("digest_date")
    if new_count >= min_refs and (not created or digest_date == last_date or _is_stub_reference_summary(digest_data)):
        digest_data = _build_fallback_digest_payload(new_refs, last_date)

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
