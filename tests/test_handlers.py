#!/usr/bin/env python3

import importlib
import json
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))


common = importlib.import_module("handlers.common")
router = importlib.import_module("handlers.router")
priority_handler = importlib.import_module("handlers.priority_handler")


class TestCommon:
    def test_build_order_defaults(self):
        order = common.build_order("lab", "run status")
        assert order["target"] == "lab"
        assert order["payload"] == "run status"
        assert order["priority"] == "normal"
        assert order["project"] == "main"
        assert order["media"] is None

    def test_resolve_project_tag(self):
        project, text = common.resolve_project("#climada run analysis")
        assert project == "climada"
        assert text == "run analysis"

    def test_resolve_project_keyword(self):
        project, text = common.resolve_project("check hazard pipeline")
        assert project == "climada"
        assert text == "check hazard pipeline"

    def test_resolve_project_default(self):
        project, text = common.resolve_project("hello world")
        assert project == "main"
        assert text == "hello world"

    def test_parse_priority_and_schedule(self):
        text, priority, scheduled_for = common.parse_priority_and_schedule(
            "🔴 ⏰2h check repository"
        )
        assert text == "check repository"
        assert priority == "urgent"
        assert isinstance(scheduled_for, str)

    def test_write_order_creates_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            order = common.build_order("lab", "run")
            path = common.write_order(base, order, message_id=12)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["payload"] == "run"

    def test_write_reference_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "ref.md"
            out = common.write_reference_markdown(
                file_path,
                "Title",
                "https://example.com",
                "body",
                {"Kind": "test"},
            )
            assert out.exists()
            text = out.read_text()
            assert "# Title" in text
            assert "**Source**: https://example.com" in text
            assert "body" in text


class TestRouter:
    def test_route_text_with_config_keywords(self):
        config = {
            "projects": {
                "research": {"keywords": ["citation", "paper"]},
            }
        }
        project, text = router.route_text("find paper summary", config)
        assert project == "research"
        assert text == "find paper summary"

    def test_route_text_tag_wins(self):
        config = {
            "projects": {
                "research": {"keywords": ["citation", "paper"]},
            }
        }
        project, text = router.route_text("#dart find paper summary", config)
        assert project == "dart"
        assert text == "find paper summary"


class TestPriorityHandler:
    def test_apply_priority_and_schedule(self):
        order = common.build_order("lab", "🔵 ⏰1d run later")
        clean_text, data = priority_handler.apply_priority_and_schedule(
            order["payload"], order
        )
        assert clean_text == "run later"
        assert data["priority"] == "low"
        assert isinstance(data["scheduled_for"], str)

    def test_validate_order_accepts_payload(self):
        order = common.build_order("lab", "run")
        validated = priority_handler.validate_order(order)
        assert validated["payload"] == "run"

    def test_validate_order_rejects_empty(self):
        order = common.build_order("lab", "")
        order["payload"] = ""
        order["media"] = None
        try:
            priority_handler.validate_order(order)
            assert False
        except ValueError:
            assert True
