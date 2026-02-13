import json
import re
from datetime import datetime, timezone
from pathlib import Path


PROJECT_TAG_PATTERN = re.compile(r"#([\w-]+)")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_order(machine_name, payload, metadata=None):
    data = {
        "type": "galaxy_order",
        "from": "galaxy-gazer",
        "target": machine_name,
        "command": "general",
        "payload": payload,
        "timestamp": now_iso(),
        "acknowledged": False,
        "priority": "normal",
        "project": "main",
        "media": None,
    }
    if metadata:
        data.update(metadata)
    return data


def write_order(orders_dir, order, message_id=None):
    orders_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    suffix = f"-{message_id}" if message_id is not None else ""
    file_path = orders_dir / f"{ts}{suffix}.json"
    file_path.write_text(json.dumps(order, indent=2))
    return file_path


def resolve_project(text, configured_projects=None):
    if not text:
        return "main", text

    tag_match = PROJECT_TAG_PATTERN.search(text)
    if tag_match:
        project_name = tag_match.group(1)
        clean_text = PROJECT_TAG_PATTERN.sub("", text).strip()
        return project_name, clean_text

    projects = configured_projects or {
        "climada": ["climada", "hazard", "impact", "exposure"],
        "dart": ["dart", "fortran", "assimilation", "ensemble"],
        "research": ["paper", "literature", "citation"],
    }
    text_lower = text.lower()
    for project_name, terms in projects.items():
        if any(term in text_lower for term in terms):
            return project_name, text

    return "main", text


def parse_priority_and_schedule(text):
    if not text:
        return text, "normal", None

    priority = "normal"
    for mark in ("🔴", "⚡"):
        if mark in text:
            priority = "urgent"
            text = text.replace(mark, "").strip()
    for mark in ("🔵", "⏸️"):
        if mark in text:
            priority = "low"
            text = text.replace(mark, "").strip()

    schedule_at = None
    schedule_match = re.search(r"⏰(\d+)([hmd])", text)
    if schedule_match:
        amount = int(schedule_match.group(1))
        unit = schedule_match.group(2)
        if unit == "h":
            delta_seconds = amount * 3600
        elif unit == "m":
            delta_seconds = amount * 60
        else:
            delta_seconds = amount * 86400
        schedule_at = datetime.now(timezone.utc).timestamp() + delta_seconds
        text = re.sub(r"⏰\d+[hmd]", "", text).strip()

    scheduled_for = (
        datetime.fromtimestamp(schedule_at, timezone.utc).isoformat()
        if schedule_at is not None
        else None
    )
    return text, priority, scheduled_for


def references_dir_for_machine(machine_config):
    return machine_config["repo_path"] / ".sisyphus" / "references"


def write_reference_markdown(path, title, source, body, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    details = metadata or {}
    lines = [f"# {title}", "", f"**Source**: {source}", f"**Ingested**: {now_iso()}"]
    for key, value in details.items():
        lines.append(f"**{key}**: {value}")
    lines.extend(["", "---", "", body, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
