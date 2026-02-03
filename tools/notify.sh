#!/bin/bash
# Galaxy-gazer notification relay
# Push Stargazer events to ntfy.sh for phone/watch/web alerts.
#
# Usage:
#   source tools/galaxy/notify.sh
#   galaxy_notify <severity> <title> <message>
#
# Severity levels: critical, warning, info, success
#
# Configuration:
#   GALAXY_TOPIC  — ntfy.sh topic name (required, set in .galaxy/config.json or env)
#   MACHINE_NAME  — machine identifier (default: hostname)
#
# Setup:
#   1. Pick a secret topic: export GALAXY_TOPIC="astraeus-$(openssl rand -hex 6)"
#   2. Install ntfy app on phone, subscribe to your topic
#   3. Test: curl -d "Hello from Galaxy-gazer" ntfy.sh/$GALAXY_TOPIC

# Load config from .galaxy/config.json if it exists
_galaxy_load_config() {
    local repo_root
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
    local config_file="${GALAXY_CONFIG:-${repo_root}/.galaxy/config.json}"

    if [ -f "$config_file" ] && command -v python3 &>/dev/null; then
        local parsed
        parsed="$(python3 - "$config_file" << 'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        c = json.load(f)
    if "ntfy_topic" in c:
        print("export GALAXY_TOPIC=" + repr(c["ntfy_topic"]))
    if "machine_name" in c:
        print("export MACHINE_NAME=" + repr(c["machine_name"]))
except Exception:
    pass
PYEOF
        )" || return 0
        eval "$parsed"
    fi
}

# Initialize on source
_galaxy_load_config

GALAXY_TOPIC="${GALAXY_TOPIC:-}"
MACHINE_NAME="${MACHINE_NAME:-$(hostname)}"

# Core notification function
galaxy_notify() {
    local severity="${1:-info}"
    local title="$2"
    local message="${3:-}"

    # Skip silently if no topic configured
    if [ -z "$GALAXY_TOPIC" ]; then
        return 0
    fi

    # Map severity to ntfy priority + emoji tags
    local priority="default"
    local tags="telescope"
    case "$severity" in
        critical) priority="urgent"; tags="rotating_light,skull" ;;
        warning)  priority="high";   tags="warning" ;;
        info)     priority="default"; tags="information_source" ;;
        success)  priority="default"; tags="white_check_mark" ;;
    esac

    curl -s \
        -H "Title: [$MACHINE_NAME] $title" \
        -H "Priority: $priority" \
        -H "Tags: $tags" \
        -d "$message" \
        "ntfy.sh/$GALAXY_TOPIC" >/dev/null 2>&1 || true
}

# Convenience wrappers
galaxy_critical() { galaxy_notify "critical" "$1" "${2:-}"; }
galaxy_warning()  { galaxy_notify "warning"  "$1" "${2:-}"; }
galaxy_info()     { galaxy_notify "info"     "$1" "${2:-}"; }
galaxy_success()  { galaxy_notify "success"  "$1" "${2:-}"; }

# Stargazer-specific event helpers
galaxy_stargazer_start() {
    local repo="$1"
    local baseline_commit="$2"
    local test_count="$3"
    galaxy_info "🔭 Stargazer Active" \
        "Monitoring ${repo}\nBaseline: ${baseline_commit}\nTests: ${test_count}"
}

galaxy_stargazer_end() {
    local commits="$1"
    local test_count="$2"
    local concerns="$3"
    galaxy_success "✅ Stargazer Report" \
        "Observed ${commits} commits\nTests: ${test_count}\nConcerns: ${concerns}"
}

galaxy_test_regression() {
    local baseline="$1"
    local current="$2"
    local commit="$3"
    galaxy_critical "🔴 Test Regression" \
        "Tests dropped ${baseline}→${current} after commit ${commit}"
}

galaxy_empty_agent() {
    local agent_file="$1"
    local lines="$2"
    galaxy_critical "🔴 Empty Agent" \
        "${agent_file} reduced to ${lines} lines"
}

galaxy_phantom_ref() {
    local file="$1"
    local phantom_path="$2"
    galaxy_warning "🟡 Phantom Reference" \
        "${file} references ${phantom_path} which doesn't exist"
}

galaxy_commit_observed() {
    local hash="$1"
    local message="$2"
    local test_count="$3"
    galaxy_info "📦 Commit: ${hash}" \
        "${message}\nTests: ${test_count}"
}
