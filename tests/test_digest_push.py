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


@pytest.mark.asyncio
async def test_send_daily_digest_uses_live_payload_when_auto_create_succeeds_but_loader_is_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_indexes(tmp_path)

    async def _always_succeed(_):
        return True

    monkeypatch.setattr(digest_push, "_attempt_agent_digest_creation", _always_succeed)

    bot = AsyncMock()
    config = {
        "features": {"GALAXY_DIGEST_PUSH_ENABLED": True},
        "digest_push": {
            "min_refs_for_auto_digest": 1,
            "digest_subscribers": [1791247114],
        },
    }

    def stub_loader():
        return {
            "patterns": [],
            "references": [{"title": "3 references processed (2026-02-23)"}],
            "actions": [],
        }

    await digest_push.send_daily_digest(bot, config, stub_loader)

    assert bot.send_message.await_count >= 1
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "Ref Alpha" in sent_text
    assert "Ref Beta" in sent_text
    assert "Auto-digest fallback used" not in sent_text


def test_new_refs_after_same_day_digest_are_detected(tmp_path, monkeypatch):
    """Regression: refs added later on the same UTC day as the last digest
    must not be invisible to _get_new_refs.

    Scenario that triggered the bug:
    - Digest created at 09:03 KST = 00:03 UTC on date X
    - User feeds refs at 17-18 UTC on date X  (= 02-03 AM KST next day)
    - _get_new_refs used cutoff = date + 'T23:59:59Z', so refs were excluded
    - Today's 9 AM scheduler fires, finds 0 new refs, skips digest
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sisyphus/digests").mkdir(parents=True)
    (tmp_path / ".sisyphus/references").mkdir(parents=True)

    # Last digest covered refs up to 00:30 UTC on 2026-02-24
    digests_index = {
        "digests": [
            {
                "date": "2026-02-24",
                "file": "digest-2026-02-24.md",
                "refs_slugs": ["early-ref"],
                "refs_processed": 1,
            }
        ]
    }
    (tmp_path / ".sisyphus/digests/index.json").write_text(
        json.dumps(digests_index), encoding="utf-8"
    )
    (tmp_path / ".sisyphus/digests/digest-2026-02-24.md").write_text(
        "# Digest: 2026-02-24\n\n## 6. References Processed\n- `early-ref`\n",
        encoding="utf-8",
    )

    # References: early-ref (covered by digest at 00:30 UTC) and two late-refs
    # added at 17:xx and 18:xx UTC — same calendar day, after the digest
    references_index = {
        "references": [
            {
                "file": "early-ref.md",
                "title": "Early Ref",
                "shared_at": "2026-02-24T00:30:00Z",
            },
            {
                "file": "late-ref-one.md",
                "title": "Late Ref One",
                "shared_at": "2026-02-24T17:49:00Z",
            },
            {
                "file": "late-ref-two.md",
                "title": "Late Ref Two",
                "shared_at": "2026-02-24T18:40:00Z",
            },
        ],
        "digests": [],
    }
    (tmp_path / ".sisyphus/references/index.json").write_text(
        json.dumps(references_index), encoding="utf-8"
    )

    cutoff = digest_push._get_last_digest_cutoff_ts()
    # Cutoff must be the max shared_at of the covered ref (00:30 UTC), not midnight
    assert cutoff == "2026-02-24T00:30:00Z"

    new_refs = digest_push._get_new_refs(cutoff)
    titles = [r["title"] for r in new_refs]
    assert "Late Ref One" in titles, "Late ref added after digest was missed"
    assert "Late Ref Two" in titles, "Late ref added after digest was missed"
    assert "Early Ref" not in titles, "Early ref should not be reprocessed"
