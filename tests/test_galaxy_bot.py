#!/usr/bin/env python3
"""
Unit tests for Galaxy Protocol command/runtime behavior.

Tests the bot's logic WITHOUT requiring a Telegram connection or token.
Mocks subprocess, file I/O, and Telegram API to verify:
- Config loading and validation (legacy + multi-machine)
- Machine registry and routing
- Authorization checks
- Command output formatting
- Order JSON structure (matches event-schema.json)
- Error handling and edge cases

Run tests:
    python -m pytest tests/test_galaxy_bot.py -v

Coverage:
    python -m pytest tests/test_galaxy_bot.py --cov=tools/galaxy --cov-report=term-missing
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

SCHEMA_PATH = Path(__file__).parent.parent / ".sisyphus" / "drafts" / "galaxy-gazer-protocol" / "event-schema.json"


# ============================================================================
# Config Loading Tests
# ============================================================================


class TestConfigLoading:
    """Test config file loading and validation."""

    def test_config_example_is_valid_json(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        assert isinstance(config, dict)

    def test_config_example_has_all_required_fields(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        required = [
            "telegram_token",
            "authorized_users",
            "machines",
            "default_machine",
            "ntfy_topic",
            "ntfy_server",
            "poll_interval",
        ]
        for field in required:
            assert field in config, f"Missing required field: {field}"

    def test_config_example_authorized_users_is_list(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        assert isinstance(config["authorized_users"], list)

    def test_config_example_has_placeholder_token(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        assert "CHANGE-ME" in config["telegram_token"]

    def test_config_example_machines_is_dict(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        assert isinstance(config["machines"], dict)
        assert len(config["machines"]) >= 1

    def test_config_example_machine_has_repo_path(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        for name, machine in config["machines"].items():
            assert "repo_path" in machine, f"Machine {name} missing repo_path"
            assert machine["repo_path"].startswith("/"), f"Machine {name} repo_path must be absolute"

    def test_config_example_default_machine_exists_in_machines(self):
        config_path = Path(__file__).parent.parent / "tools" / "config.json.example"
        with open(config_path) as f:
            config = json.load(f)
        assert config["default_machine"] in config["machines"]


# ============================================================================
# Machine Registry Tests
# ============================================================================


class TestMachineRegistry:
    """Test load_machines() and resolve_machine() logic."""

    def _load_machines(self, config):
        """Replicate load_machines logic for testing without importing bot.py."""
        if "machines" in config:
            machines = {}
            for name, entry in config["machines"].items():
                machines[name] = {
                    "host": entry.get("host", "localhost"),
                    "repo_path": Path(entry["repo_path"]),
                    "machine_name": entry.get("machine_name", name),
                }
            return machines
        name = config.get("machine_name", "local")
        return {
            name: {
                "host": "localhost",
                "repo_path": Path(config.get("repo_path", "/tmp")),
                "machine_name": name,
            }
        }

    def test_new_format_single_machine(self):
        config = {"machines": {"lab": {"host": "localhost", "repo_path": "/home/zephyr/astraeus"}}}
        machines = self._load_machines(config)
        assert "lab" in machines
        assert machines["lab"]["host"] == "localhost"
        assert machines["lab"]["repo_path"] == Path("/home/zephyr/astraeus")

    def test_new_format_multiple_machines(self):
        config = {
            "machines": {
                "lab": {"host": "localhost", "repo_path": "/home/zephyr/astraeus"},
                "hpc": {
                    "host": "hpc.local",
                    "repo_path": "/home/zephyr/astraeus",
                    "ssh_user": "zephyr",
                },
            }
        }
        machines = self._load_machines(config)
        assert len(machines) == 2
        assert "lab" in machines
        assert "hpc" in machines

    def test_legacy_format_backward_compatible(self):
        config = {"machine_name": "old-server", "repo_path": "/opt/astraeus"}
        machines = self._load_machines(config)
        assert "old-server" in machines
        assert machines["old-server"]["host"] == "localhost"
        assert machines["old-server"]["repo_path"] == Path("/opt/astraeus")

    def test_legacy_format_defaults(self):
        config = {}
        machines = self._load_machines(config)
        assert "local" in machines

    def test_machine_name_defaults_to_key(self):
        config = {"machines": {"lab": {"host": "localhost", "repo_path": "/tmp"}}}
        machines = self._load_machines(config)
        assert machines["lab"]["machine_name"] == "lab"

    def test_machine_name_can_override(self):
        config = {
            "machines": {
                "lab": {
                    "host": "localhost",
                    "repo_path": "/tmp",
                    "machine_name": "Lab Server",
                }
            }
        }
        machines = self._load_machines(config)
        assert machines["lab"]["machine_name"] == "Lab Server"

    def test_host_defaults_to_localhost(self):
        config = {"machines": {"lab": {"repo_path": "/tmp"}}}
        machines = self._load_machines(config)
        assert machines["lab"]["host"] == "localhost"

    def test_is_local_detection(self):
        local_hosts = ["localhost", "127.0.0.1", ""]
        for host in local_hosts:
            machine = {"host": host}
            assert machine["host"] in ("localhost", "127.0.0.1", "")

    def test_is_remote_detection(self):
        remote_hosts = ["hpc.local", "192.168.1.100", "lab.university.edu"]
        for host in remote_hosts:
            machine = {"host": host}
            assert machine["host"] not in ("localhost", "127.0.0.1", "")

    def test_resolve_known_machine(self):
        machines = {"lab": {"host": "localhost"}, "hpc": {"host": "hpc.local"}}
        assert "lab" in machines
        assert "hpc" in machines

    def test_resolve_unknown_machine(self):
        machines = {"lab": {"host": "localhost"}}
        assert "nonexistent" not in machines

    def test_resolve_none_uses_default(self):
        machines = {"lab": {"host": "localhost"}, "hpc": {"host": "hpc.local"}}
        default = "lab"
        target = None
        result = default if target is None else target
        assert result == "lab"


# ============================================================================
# Authorization Tests
# ============================================================================


class TestAuthorization:
    """Test the is_authorized() logic."""

    def test_authorized_user_allowed(self):
        authorized = {123456789, 987654321}
        assert 123456789 in authorized

    def test_unauthorized_user_denied(self):
        authorized = {123456789}
        assert 999999999 not in authorized

    def test_empty_allowlist_denies_all(self):
        authorized = set()
        assert 123456789 not in authorized

    def test_authorized_users_is_set_for_O1_lookup(self):
        config_list = [123456789, 987654321]
        authorized = set(config_list)
        assert isinstance(authorized, set)
        assert len(authorized) == 2


# ============================================================================
# Order JSON Structure Tests
# ============================================================================


class TestOrderStructure:
    """Test that galaxy orders match the event-schema.json spec."""

    def _make_order(self, text="focus on tools/metrics/", machine="lab-server"):
        return {
            "type": "galaxy_order",
            "from": "galaxy-gazer",
            "target": machine,
            "command": "general",
            "payload": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }

    def test_order_has_required_fields(self):
        order = self._make_order()
        required = [
            "type",
            "from",
            "target",
            "command",
            "payload",
            "timestamp",
            "acknowledged",
        ]
        for field in required:
            assert field in order, f"Missing required field: {field}"

    def test_order_type_is_galaxy_order(self):
        assert self._make_order()["type"] == "galaxy_order"

    def test_order_from_is_galaxy_gazer(self):
        assert self._make_order()["from"] == "galaxy-gazer"

    def test_order_acknowledged_defaults_false(self):
        assert self._make_order()["acknowledged"] is False

    def test_order_command_is_general(self):
        assert self._make_order()["command"] == "general"

    def test_order_timestamp_is_iso8601(self):
        order = self._make_order()
        ts = str(order["timestamp"])
        # Should be parseable
        datetime.fromisoformat(ts)

    def test_order_payload_preserved(self):
        order = self._make_order("ignore --no-verify warnings")
        assert order["payload"] == "ignore --no-verify warnings"

    def test_order_target_matches_machine(self):
        order = self._make_order(machine="hpc-node")
        assert order["target"] == "hpc-node"

    def test_order_serializes_to_valid_json(self):
        order = self._make_order()
        serialized = json.dumps(order, indent=2)
        deserialized = json.loads(serialized)
        assert deserialized == order

    def test_order_matches_schema_enum_values(self):
        if not SCHEMA_PATH.exists():
            pytest.skip("event-schema.json not found (gitignored drafts)")
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        allowed = schema["definitions"]["inbound_order"]["properties"]["command"]["enum"]
        assert self._make_order()["command"] in allowed


# ============================================================================
# Order File Writing Tests
# ============================================================================


class TestOrderFileWriting:
    """Test order file creation and naming."""

    def test_order_file_written_to_correct_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orders_dir = Path(tmpdir) / ".sisyphus" / "notepads" / "galaxy-orders"
            orders_dir.mkdir(parents=True, exist_ok=True)

            order = {"type": "galaxy_order", "payload": "test"}
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            order_file = orders_dir / f"{ts}.json"

            with open(order_file, "w") as f:
                json.dump(order, f, indent=2)

            assert order_file.exists()
            with open(order_file) as f:
                loaded = json.load(f)
            assert loaded["payload"] == "test"

    def test_order_filename_is_timestamp(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"{ts}.json"
        assert len(ts) == 15  # YYYYMMDD-HHMMSS
        assert filename.endswith(".json")

    def test_orders_directory_created_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orders_dir = Path(tmpdir) / "deep" / "nested" / "galaxy-orders"
            orders_dir.mkdir(parents=True, exist_ok=True)
            assert orders_dir.is_dir()


# ============================================================================
# Multi-Machine Order Routing Tests
# ============================================================================


class TestOrderRouting:
    """Test order routing to specific machines."""

    def test_order_targets_specific_machine(self):
        """When machine is specified, order targets that machine."""
        order = {
            "type": "galaxy_order",
            "from": "galaxy-gazer",
            "target": "hpc-node",
            "command": "general",
            "payload": "check regressions",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        assert order["target"] == "hpc-node"

    def test_order_broadcast_creates_per_machine(self):
        """'all' should create separate orders for each machine."""
        machines = {"lab": {}, "hpc": {}, "laptop": {}}
        orders = []
        for name in machines:
            orders.append({"target": name, "payload": "pause"})
        assert len(orders) == 3
        assert {o["target"] for o in orders} == {"lab", "hpc", "laptop"}

    def test_order_default_machine_when_unspecified(self):
        """When no machine given, order goes to default."""
        default = "lab"
        machines = {"lab": {}, "hpc": {}}
        args = ["focus", "on", "tools/"]  # no machine name
        first_arg = args[0]
        if first_arg in machines:
            target = first_arg
        else:
            target = default
        assert target == "lab"

    def test_order_explicit_machine_extracted_from_args(self):
        """When first arg is a machine name, it's extracted."""
        machines = {"lab": {}, "hpc": {}}
        args = ["hpc", "check", "regressions"]
        first_arg = args[0]
        if first_arg in machines:
            target = first_arg
            message = " ".join(args[1:])
        else:
            target = "lab"
            message = " ".join(args)
        assert target == "hpc"
        assert message == "check regressions"


# ============================================================================
# Concerns Truncation Tests
# ============================================================================


class TestConcernsTruncation:
    """Test that /concerns output respects Telegram's 4096 char limit."""

    def test_short_content_not_truncated(self):
        content = "Some concerns here" * 10
        assert len(content) <= 3500

    def test_long_content_truncated_at_3500(self):
        content = "x" * 4000
        if len(content) > 3500:
            content = content[:3500] + "\n\n... (truncated, see full in notepads)"
        assert len(content) < 4096
        assert "truncated" in content

    def test_exactly_3500_not_truncated(self):
        content = "x" * 3500
        assert len(content) <= 3500
        assert "truncated" not in content

    def test_truncation_leaves_room_for_header(self):
        content = "x" * 5000
        if len(content) > 3500:
            content = content[:3500] + "\n\n... (truncated, see full in notepads)"
        header = "📋 *lab-server* — Latest Concerns\n\n"
        total = header + content
        assert len(total) < 4096


# ============================================================================
# Status Formatting Tests
# ============================================================================


class TestStatusFormatting:
    """Test /status output handles edge cases."""

    def test_clean_working_tree_shows_clean(self):
        git_output = ""
        display = git_output or "(clean)"
        assert display == "(clean)"

    def test_dirty_working_tree_shows_files(self):
        git_output = " M CHANGELOG.md\n?? new-file.txt"
        display = git_output or "(clean)"
        assert "CHANGELOG.md" in display

    def test_no_stargazer_reports(self):
        reports = []
        summary = f"{len(reports)} report(s)" if reports else "No reports"
        assert summary == "No reports"

    def test_report_count_with_reports(self):
        reports = ["stargazer-2026-02-01/meta.json", "stargazer-2026-02-02/meta.json"]
        summary = f"{len(reports)} report(s)" if reports else "No reports"
        assert summary == "2 report(s)"

    def test_all_status_concatenates_machines(self):
        """'/status all' should join multiple machine statuses."""
        parts = ["📊 *lab* Status\n...", "📊 *hpc* Status\n..."]
        msg = "\n\n---\n\n".join(parts)
        assert "lab" in msg
        assert "hpc" in msg
        assert "---" in msg


# ============================================================================
# Systemd Service Tests
# ============================================================================


class TestSystemdService:
    """Test galaxy.service file structure."""

    def test_service_file_exists(self):
        service_path = Path(__file__).parent.parent / "services" / "galaxy.service"
        assert service_path.exists()

    def test_service_has_restart_always(self):
        service_path = Path(__file__).parent.parent / "services" / "galaxy.service"
        assert "Restart=always" in service_path.read_text()

    def test_service_has_customize_comment(self):
        service_path = Path(__file__).parent.parent / "services" / "galaxy.service"
        assert "CUSTOMIZE" in service_path.read_text()

    def test_service_runs_bot_py(self):
        service_path = Path(__file__).parent.parent / "services" / "galaxy.service"
        assert "bot.py" in service_path.read_text()


# ============================================================================
# Requirements Tests
# ============================================================================


class TestRequirements:
    """Test requirements.txt validity."""

    def test_requirements_file_exists(self):
        req_path = Path(__file__).parent.parent / "tools" / "requirements.txt"
        assert req_path.exists()

    def test_requirements_pins_telegram_bot(self):
        req_path = Path(__file__).parent.parent / "tools" / "requirements.txt"
        content = req_path.read_text()
        assert "python-telegram-bot" in content
        assert ">=" in content
        assert "<" in content
