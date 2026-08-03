"""Shared chatbot KB service — alias for single import path."""

from app.services.chatbot_cskh_kb_service import (  # noqa: F401
    create_kb_node,
    delete_kb_node,
    get_kb_for_bot,
    get_or_create_map,
    import_kb_from_sources,
    import_kb_items,
    import_kb_text,
    import_kb_xlsx,
    list_import_sources,
    search_kb_nodes,
    toggle_kb_node,
    update_kb_node,
)

__all__ = [
    "create_kb_node",
    "delete_kb_node",
    "get_kb_for_bot",
    "get_or_create_map",
    "import_kb_from_sources",
    "import_kb_items",
    "import_kb_text",
    "import_kb_xlsx",
    "list_import_sources",
    "search_kb_nodes",
    "toggle_kb_node",
    "update_kb_node",
]
