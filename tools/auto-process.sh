#!/bin/bash
# Simple Galaxy Order Auto-Processor
# Polls for orders and executes them automatically

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORDERS_DIR="$REPO_ROOT/.sisyphus/notepads/galaxy-orders"
ARCHIVE_DIR="$REPO_ROOT/.sisyphus/notepads/galaxy-orders-archive"
RESPONSE_DIR="$REPO_ROOT/.sisyphus/notepads"
OUTBOX_DIR="$REPO_ROOT/.sisyphus/notepads/galaxy-outbox"
POLL_INTERVAL=30

echo "🌌 Galaxy Auto-Processor Starting..."
echo "📂 Watching: $ORDERS_DIR"
echo "⏱  Interval: ${POLL_INTERVAL}s"
echo ""

process_order() {
    local order_file="$1"
    local order_id="$(basename "$order_file" .json)"
    
    echo "📨 Processing order: $order_id"
    
    # Read order
    local payload=$(jq -r '.payload' "$order_file")
    local timestamp=$(jq -r '.timestamp' "$order_file")
    
    # Execute via opencode
    echo "🤖 Executing: $payload"
    local response=$(timeout 120 opencode run --attach http://localhost:4096 --format json "$payload" 2>&1 || echo "Execution failed")
    
    # Extract response text
    local response_text=$(echo "$response" | jq -r '.part.text // empty' | tail -1)
    if [ -z "$response_text" ]; then
        response_text="$response"
    fi
    
    # Write response file
    cat > "$RESPONSE_DIR/galaxy-order-response-$order_id.md" <<EOF
# Galaxy Order Response

**Order Received**: $timestamp  
**Message**: "$payload"  
**Acknowledged By**: Auto-Processor

---

## Response

$response_text

---

**Galaxy Auto-Processor**  
$(date -u +%Y-%m-%dT%H:%M:%S%z)
EOF
    
    # Archive order
    mkdir -p "$ARCHIVE_DIR"
    jq '. + {acknowledged: true, acknowledged_at: "'$(date -u +%Y-%m-%dT%H:%M:%S%z)'", acknowledged_by: "Auto-Processor"}' "$order_file" > "$ARCHIVE_DIR/$order_id.json"
    rm "$order_file"
    
    # Send to outbox
    mkdir -p "$OUTBOX_DIR"
    cat > "$OUTBOX_DIR/response-$order_id.json" <<EOF
{
  "type": "notification",
  "severity": "success",
  "from": "Galaxy Auto-Processor",
  "message": "✅ <b>Order Executed</b>\n\n<code>$(echo "$payload" | head -c 80)</code>\n\n<b>Response:</b> $(echo "$response_text" | head -c 100)",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S%z)",
  "sent": false
}
EOF
    
    echo "✅ Order $order_id processed"
}

# Main loop
while true; do
    if compgen -G "$ORDERS_DIR/*.json" > /dev/null; then
        for order_file in "$ORDERS_DIR"/*.json; do
            [ -e "$order_file" ] || continue
            
            # Skip if already processing
            [ -e "${order_file}.processing" ] && continue
            
            process_order "$order_file" &
        done
    fi
    
    sleep "$POLL_INTERVAL"
done
