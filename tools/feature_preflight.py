#!/usr/bin/env python3

import importlib
import json
import sys
from pathlib import Path


CONFIG_PATH = Path(__file__).parent.parent.parent / ".galaxy" / "config.json"


def _load_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())


def _check_import(name):
    try:
        importlib.import_module(name)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _check_command(name):
    from shutil import which

    return which(name) is not None


def _check_opencode_runtime():
    try:
        runtime = importlib.import_module("opencode_runtime")
        binary, error = runtime.resolve_opencode_binary()
        if binary:
            return True, binary
        return False, error or "opencode binary unavailable"
    except Exception as exc:
        return False, str(exc)


def main():
    config = _load_config()
    features = config.get("features", {})

    checks = []

    if features.get("GALAXY_DEEPWIKI_ENABLED", False):
        checks.append(("opencode_cli", *_check_opencode_runtime()))
        checks.append(("deepwiki_client", *_check_import("deepwiki_client")))

    if features.get("GALAXY_VOICE_ENABLED", False):
        checks.append(("faster_whisper", *_check_import("faster_whisper")))
        checks.append(("ffmpeg", _check_command("ffmpeg"), "missing ffmpeg"))

    if features.get("GALAXY_IMAGE_PDF_ENABLED", False):
        checks.append(("pytesseract", *_check_import("pytesseract")))
        checks.append(("PIL", *_check_import("PIL")))
        checks.append(("cv2", *_check_import("cv2")))
        checks.append(("pdfplumber", *_check_import("pdfplumber")))
        checks.append(("docker", *_check_import("docker")))
        checks.append(("tesseract", _check_command("tesseract"), "missing tesseract"))

    if features.get("GALAXY_PRIORITY_SCHEDULING_ENABLED", False):
        checks.append(("jsonschema", *_check_import("jsonschema")))

    if features.get("GALAXY_DIGEST_PUSH_ENABLED", False):
        checks.append(("apscheduler", *_check_import("apscheduler")))
        checks.append(("sqlalchemy", *_check_import("sqlalchemy")))

    if not checks:
        print("No feature flags enabled; preflight skipped")
        return 0

    failed = []
    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}")
        if not ok:
            failed.append((name, detail))

    if failed:
        print("\nMissing requirements:")
        for name, detail in failed:
            print(f"- {name}: {detail}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
