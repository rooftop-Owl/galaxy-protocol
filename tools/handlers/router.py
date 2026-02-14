import importlib


common = importlib.import_module("handlers.common")


def route_text(order_text, config):
    configured = config.get("projects", {})
    keywords = {}
    for project_name, project_config in configured.items():
        terms = project_config.get("keywords", [])
        if terms:
            keywords[project_name] = terms
    return common.resolve_project(order_text, keywords or None)
