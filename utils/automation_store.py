"""Automation store — re-exports from src.db.automation_repository.

Convenience module so callers can use:
    from utils.automation_store import save_automation
"""

from src.db.automation_repository import (  # noqa: F401
    delete_automation,
    find_by_name,
    get_all_automations,
    get_automation,
    save_automation,
    toggle_automation,
    update_automation,
    update_run_result,
)

__all__ = [
    "save_automation",
    "get_automation",
    "get_all_automations",
    "find_by_name",
    "toggle_automation",
    "update_automation",
    "delete_automation",
    "update_run_result",
]
