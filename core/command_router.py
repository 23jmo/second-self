"""Route accepted suggestions to the appropriate handler.

Stub — the real implementation will dispatch to the agent server
or automation orchestrator.
"""

import logging
from typing import Any

log = logging.getLogger("second-self")


async def handle_input(user_id: str, suggestion: dict[str, Any]) -> str:
    """Execute an accepted suggestion.

    TODO: implement actual command routing (dispatch to agent server,
    create automations, schedule calendar events, etc.)
    """
    text = suggestion.get("text", "unknown action")
    stype = suggestion.get("type", "unknown")
    log.info(
        "Routing accepted suggestion for user %s: [%s] %s",
        user_id[:12], stype, text,
    )
    return f"Queued: {text}"
