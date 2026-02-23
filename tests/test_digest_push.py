#!/usr/bin/env python3

import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

digest_push = importlib.import_module("handlers.digest_push")


def _seed_indexes(root: Path) -> list[dict[str, Any]]:
    (root / ".sisyphus/digests").mkdir(parents=True, exist_ok=True)
    (root / ".sisyphus/references").mkdir(parents=True, exist_ok=True)

    refs = [
        {
            "file": "slug-alpha.md",
            "title": "Ref Alpha",
            "type": "repo",
            "tags": ["agents", "routing"],
            "shared_at": "2026-02-23T00:10:00Z",
        },
        {
            "file": "slug-beta.md",
            "title": "Ref Beta",
            "type": "article",
            "tags": ["agents"],
            "shared_at": "2026-02-23T00:20:00Z",
        },
        {
            "file": "slug-gamma.md",
            "title": "Ref Gamma",
            "type": "repo",
            "tags": ["memory"],
            "shared_at": "2026-02-23T00:30:00Z",
        },
    ]

    references_index = {
        "references": refs,
        "digests": [
            {
                "date": "2026-02-22",
                "refs_processed": 1,
                "refs_slugs": ["old-slug"],
                "digest_file": ".sisyphus/digests/digest-2026-02-22.md",
            }
        ],
    }
    digests_index = {
        "digests": [
            {
                "date": "2026-02-22",
                "file": "digest-2026-02-22.md",
                "themes": ["Previous"],
                "refs_slugs": ["old-slug"],
                "refs_processed": 1,
            }
        ]
    }

    (root / ".sisyphus/references/index.json").write_text(json.dumps(references_index), encoding="utf-8")
    (root / ".sisyphus/digests/index.json").write_text(json.dumps(digests_index), encoding="utf-8")

    (root / ".sisyphus/digests/digest-2026-02-22.md").write_text(
        "# Digest: 2026-02-22\n\n## 6. References Processed\n- `old-slug`\n",
        encoding="utf-8",
    )

    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools/digest_indexer.py").write_text(
        """
import json
from pathlib import Path

digests_dir = Path('.sisyphus/digests')
entries = []
for digest_file in sorted(digests_dir.glob('digest-*.md')):
    entries.append({'date': '2026-02-23', 'file': digest_file.name})

payload = {'version': '1.0', 'digests': entries}
(digests_dir / 'index.json').write_text(json.dumps(payload), encoding='utf-8')
print('ok')
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return refs


def test_create_fallback_digest_writes_file_and_updates_indexes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    refs = _seed_indexes(tmp_path)

    ok = digest_push._create_fallback_digest("2026-02-22", refs)
    assert ok is True

    today = digest_push._today_kst()
    digest_file = f"digest-{today}-auto.md"
    digest_path = tmp_path / ".sisyphus/digests" / digest_file
    assert digest_path.exists()

    references_index = json.loads((tmp_path / ".sisyphus/references/index.json").read_text())
    assert any(d.get("digest_file") == f".sisyphus/digests/{digest_file}" for d in references_index.get("digests", []))

    digests_index = json.loads((tmp_path / ".sisyphus/digests/index.json").read_text())
    assert any(d.get("file") == digest_file for d in digests_index.get("digests", []))


@pytest.mark.asyncio
async def test_send_daily_digest_uses_live_payload_when_auto_create_stays_stale(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_indexes(tmp_path)

    async def _always_fail(_):
        return False

    monkeypatch.setattr(digest_push, "_attempt_agent_digest_creation", _always_fail)

    bot = AsyncMock()
    config = {
        "features": {"GALAXY_DIGEST_PUSH_ENABLED": True},
        "digest_push": {
            "min_refs_for_auto_digest": 1,
            "digest_subscribers": [1791247114],
        },
    }

    def stale_loader():
        return {
            "digest_date": "2026-02-22",
            "patterns": [],
            "references": [{"title": "stale digest summary"}],
            "actions": [],
        }

    await digest_push.send_daily_digest(bot, config, stale_loader)

    assert bot.send_message.await_count >= 1
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "Ref Alpha" in sent_text
    assert "Ref Beta" in sent_text
    assert "stale digest summary" not in sent_text
