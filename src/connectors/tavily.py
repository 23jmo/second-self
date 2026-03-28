"""Tavily web search connector.

Fires immediately on onboarding — shows the user something true about
themselves within seconds, before Gmail/Calendar even loads.
"""

import os

import httpx


async def search_user(name: str, context: str = "") -> str:
    """Search for public info about a person.

    Args:
        name: The person's name.
        context: Optional extra context — company, Twitter handle, etc.

    Returns:
        Concatenated search result content.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return ""

    query = f"{name} {context}".strip()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5,
            },
        )
        resp.raise_for_status()

    results = resp.json().get("results", [])
    return "\n\n".join(r.get("content", "") for r in results)
