import jsonschema
import importlib

common = importlib.import_module("handlers.common")


ORDER_SCHEMA = {
    "type": "object",
    "required": [
        "type",
        "from",
        "target",
        "command",
        "timestamp",
        "acknowledged",
        "priority",
        "project",
        "media",
    ],
    "properties": {
        "priority": {"type": "string", "enum": ["urgent", "normal", "low"]},
        "project": {"type": "string"},
        "media": {},
        "scheduled_for": {"type": ["string", "null"]},
    },
}


def apply_priority_and_schedule(order_text, order_data):
    clean_text, priority, scheduled_for = common.parse_priority_and_schedule(order_text)
    order_data["payload"] = clean_text
    order_data["priority"] = priority
    if scheduled_for:
        order_data["scheduled_for"] = scheduled_for
    return clean_text, order_data


def validate_order(order_data):
    jsonschema.validate(order_data, ORDER_SCHEMA)
    if not order_data.get("payload") and not order_data.get("media"):
        raise ValueError("Order must include payload or media")
    return order_data
