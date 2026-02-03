#!/usr/bin/env python3
"""
Galaxy Protocol Monitoring Dashboard

Simple Flask web dashboard showing Galaxy system health and metrics.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent  # project root (when loaded as submodule)
MODULE_ROOT = Path(__file__).parent.parent  # galaxy-protocol module root
ORDERS_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders"
ARCHIVE_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-orders-archive"
OUTBOX_DIR = REPO_ROOT / ".sisyphus/notepads/galaxy-outbox"
HEALTH_LOG = REPO_ROOT / "logs/galaxy-health.log"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Galaxy Protocol Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e27;
            color: #e0e6f0;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            text-align: center;
        }
        h1 { font-size: 2.5em; font-weight: 700; margin-bottom: 10px; }
        .subtitle { opacity: 0.9; font-size: 1.1em; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
        }
        .card h2 {
            font-size: 1.3em;
            margin-bottom: 20px;
            color: #a5b4fc;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #9ca3af; font-size: 0.95em; }
        .metric-value {
            font-size: 1.8em;
            font-weight: 700;
            color: #fff;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-left: 8px;
        }
        .status-healthy { background: #10b981; box-shadow: 0 0 10px #10b981; }
        .status-warning { background: #f59e0b; box-shadow: 0 0 10px #f59e0b; }
        .status-error { background: #ef4444; box-shadow: 0 0 10px #ef4444; }
        .logs {
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            padding: 16px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.85em;
            max-height: 300px;
            overflow-y: auto;
            color: #d1d5db;
        }
        .log-line { padding: 4px 0; }
        .timestamp { color: #6b7280; }
        footer {
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #6b7280;
            font-size: 0.9em;
        }
        .refresh-note {
            text-align: center;
            margin-top: 10px;
            color: #9ca3af;
            font-size: 0.9em;
        }
    </style>
    <script>
        function refreshData() {
            fetch('/api/status')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('pending').textContent = data.pending;
                    document.getElementById('processed').textContent = data.processed;
                    document.getElementById('failed').textContent = data.failed;
                    document.getElementById('uptime').textContent = data.uptime_human;
                    
                    const healthStatus = document.getElementById('health-status');
                    healthStatus.className = 'status-indicator status-' + 
                        (data.opencode_healthy && data.galaxy_mcp_running ? 'healthy' : 'error');
                    
                    document.getElementById('last-update').textContent = 
                        new Date().toLocaleTimeString();
                });
        }
        
        setInterval(refreshData, 10000);
        setTimeout(refreshData, 1000);
    </script>
</head>
<body>
    <div class="container">
        <header>
            <h1>⭐ Galaxy Protocol</h1>
            <p class="subtitle">System Monitoring Dashboard</p>
        </header>
        
        <div class="grid">
            <div class="card">
                <h2>System Status <span id="health-status" class="status-indicator status-{{ 'healthy' if status.opencode_healthy and status.galaxy_mcp_running else 'error' }}"></span></h2>
                <div class="metric">
                    <span class="metric-label">Uptime</span>
                    <span class="metric-value" id="uptime">{{ status.uptime_human }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">OpenCode Server</span>
                    <span class="metric-value">{{ '✓' if status.opencode_healthy else '✗' }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Galaxy MCP</span>
                    <span class="metric-value">{{ '✓' if status.galaxy_mcp_running else '✗' }}</span>
                </div>
            </div>
            
            <div class="card">
                <h2>Order Metrics</h2>
                <div class="metric">
                    <span class="metric-label">Pending</span>
                    <span class="metric-value" id="pending">{{ status.pending }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Processed</span>
                    <span class="metric-value" id="processed">{{ status.processed }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Failed</span>
                    <span class="metric-value" id="failed">{{ status.failed }}</span>
                </div>
            </div>
            
            <div class="card">
                <h2>Resource Usage</h2>
                <div class="metric">
                    <span class="metric-label">Disk Usage</span>
                    <span class="metric-value">{{ status.disk_usage }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Outbox Alerts</span>
                    <span class="metric-value">{{ status.outbox_count }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Machine</span>
                    <span class="metric-value" style="font-size: 1.2em;">{{ status.machine }}</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Recent Health Logs</h2>
            <div class="logs">
                {% for log in logs %}
                <div class="log-line">{{ log }}</div>
                {% endfor %}
            </div>
        </div>
        
        <footer>
            <p class="refresh-note">Auto-refresh every 10 seconds | Last update: <span id="last-update">{{ status.timestamp }}</span></p>
            <p>Galaxy Protocol Dashboard v1.0 | Phase D1</p>
        </footer>
    </div>
</body>
</html>
"""


def get_disk_usage():
    try:
        result = subprocess.run(
            ["df", str(REPO_ROOT)], capture_output=True, text=True, timeout=2
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            usage = parts[4].rstrip("%")
            return int(usage)
    except (subprocess.SubprocessError, ValueError, IndexError):
        pass
    return 0


def check_galaxy_mcp_running():
    try:
        result = subprocess.run(
            ["pgrep", "-f", "galaxy_mcp.py"], capture_output=True, timeout=2
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def get_recent_logs(lines=20):
    if not HEALTH_LOG.exists():
        return ["No health check logs yet"]

    try:
        with open(HEALTH_LOG, "r") as f:
            all_lines = f.readlines()
            return [line.strip() for line in all_lines[-lines:]]
    except (OSError, IOError):
        return ["Error reading logs"]


def get_status():
    pending = 0
    if ORDERS_DIR.exists():
        pending = len(list(ORDERS_DIR.glob("*.json")))

    processed = 0
    if ARCHIVE_DIR.exists():
        processed = len(list(ARCHIVE_DIR.glob("*.json")))

    outbox_count = 0
    if OUTBOX_DIR.exists():
        outbox_count = len(list(OUTBOX_DIR.glob("*.json")))

    opencode_healthy = False
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "http://localhost:4096/health",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        opencode_healthy = result.stdout == "200"
    except (subprocess.SubprocessError, OSError):
        pass

    galaxy_mcp_running = check_galaxy_mcp_running()

    machine_name = "unknown"
    try:
        config_file = REPO_ROOT / ".galaxy/config.json"
        if config_file.exists():
            config = json.loads(config_file.read_text())
            machine_name = config.get("default_machine", "unknown")
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    return {
        "pending": pending,
        "processed": processed,
        "failed": 0,
        "uptime_human": "N/A",
        "opencode_healthy": opencode_healthy,
        "galaxy_mcp_running": galaxy_mcp_running,
        "disk_usage": get_disk_usage(),
        "outbox_count": outbox_count,
        "machine": machine_name,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/")
def dashboard():
    status = get_status()
    logs = get_recent_logs()
    return render_template_string(DASHBOARD_HTML, status=status, logs=logs)


@app.route("/api/status")
def api_status():
    return jsonify(get_status())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
