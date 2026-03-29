"""
SuggestionEngine — generates proactive suggestions for the Second Self twin.

Three trigger modes:
  1. Profile-based (Layer 1): fires after Tavily profiles a person
  2. Pattern-based (Layer 2): fires after each job completes
  3. Ambient (Layer 3): background loop every 30s with desktop screenshot

All suggestions are pushed to the SwiftUI app via the persistent /events SSE channel.
Reward signals (accept/dismiss) are stored in rewards.jsonl for future RL training.
"""

import json
import os
import pathlib
import time
import uuid

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

CONFIDENCE_THRESHOLD = 0.7
MAX_SUGGESTIONS_PER_MINUTE = 3
REWARDS_PATH = pathlib.Path.home() / ".secondself" / "rewards.jsonl"


_anthropic_client = None


def _get_client():
    """Reuse a single Anthropic client instance."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def _call_claude_sync(system_prompt: str, user_content) -> str:
    """Synchronous Anthropic SDK call for suggestion generation. Returns raw text."""
    if not ANTHROPIC_API_KEY:
        return ""

    try:
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""
    except Exception as e:
        print(f"[suggestion_engine] Claude API error: {e}")
        return ""


def _parse_suggestions(text: str) -> list[dict]:
    """Parse Claude text response into a list of suggestion dicts."""
    if not text:
        return []
    try:
        # Extract JSON from response (may be wrapped in markdown code block)
        content = text.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content)
        if isinstance(parsed, list):
            suggestions = parsed
        elif isinstance(parsed, dict) and "suggestions" in parsed:
            suggestions = parsed["suggestions"]
        else:
            return []

        result = []
        for s in suggestions:
            confidence = float(s.get("confidence", 0.5))
            if confidence < CONFIDENCE_THRESHOLD:
                continue
            # Stringify context values to match Swift's [String: String] type
            raw_context = s.get("context", {})
            context = {str(k): str(v) for k, v in raw_context.items()} if isinstance(raw_context, dict) else {}
            result.append({
                "id": f"sug_{uuid.uuid4().hex[:8]}",
                "title": s.get("title", "Suggestion"),
                "description": s.get("description", ""),
                "confidence": confidence,
                "action_id": s.get("action_id", "general"),
                "context": context,
            })
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def profile_trigger(profile: dict) -> list[dict]:
    """
    Layer 1: Generate suggestions based on Tavily profile data.
    Called once after profiling completes.
    Returns a list of suggestion dicts ready for SSE broadcast.
    """
    if not profile:
        return []

    name = profile.get("name", "the user")
    title = profile.get("title", "")
    company = profile.get("company", "")
    interests = profile.get("interests", [])
    recent_activity = profile.get("recent_activity", "")
    bio = profile.get("bio", "")

    prompt = (
        "You are a proactive digital twin. A new user just arrived. "
        "Based on their profile, generate 2-3 specific, actionable workflow suggestions.\n\n"
        "Each suggestion should be something you can execute on a macOS desktop "
        "(browser research, document creation, data compilation).\n\n"
        f"User profile:\n"
        f"  Name: {name}\n"
        f"  Title: {title}\n"
        f"  Company: {company}\n"
        f"  Interests: {', '.join(interests) if interests else 'general technology'}\n"
        f"  Recent activity: {recent_activity}\n"
        f"  Bio: {bio}\n\n"
        "Return a JSON object with a 'suggestions' array. Each suggestion has:\n"
        "  title (short, action-oriented), description (1-2 sentences, used as task prompt),\n"
        "  confidence (0.0-1.0), action_id (semantic label like 'research_competitors'),\n"
        "  context (dict with relevant details like company, industry).\n"
        "Only suggest things with confidence >= 0.7."
    )

    text = _call_claude_sync(prompt, "Generate suggestions for this user.")
    suggestions = _parse_suggestions(text)

    # Tag all with source
    for s in suggestions:
        s["source"] = "profile"

    print(f"[suggestion_engine] Profile trigger: {len(suggestions)} suggestions for {name}")
    return suggestions


def pattern_trigger(conversation_history: list[dict], profile: dict | None = None) -> list[dict]:
    """
    Layer 2: Detect patterns in conversation history.
    Called after each job completes. Only suggests if 3+ requests share verb+object type.
    Returns a list of suggestion dicts (usually 0 or 1).
    """
    # Need at least 3 genuine user messages (skip suggestion-originated ones to prevent self-reinforcing loops)
    user_messages = [m["content"] for m in conversation_history if m.get("role") == "user" and m.get("source", "user") == "user"]
    if len(user_messages) < 3:
        return []

    profile_summary = ""
    if profile:
        profile_summary = f"User: {profile.get('name', '')}, {profile.get('title', '')} at {profile.get('company', '')}"

    prompt = (
        "You are a proactive digital twin analyzing conversation patterns.\n\n"
        "Here are the user's recent requests (oldest first):\n"
        + "\n".join(f"  {i+1}. {msg}" for i, msg in enumerate(user_messages[-10:]))
        + "\n\n"
        + (f"User profile: {profile_summary}\n\n" if profile_summary else "")
        + "Look for patterns: repeated request types, similar themes, escalating specificity.\n"
        "ONLY suggest a pattern if 3+ requests clearly share the same verb + object type.\n"
        "If no clear pattern exists, return {\"suggestions\": []}.\n"
        "If a pattern exists, return a JSON object with a 'suggestions' array containing ONE suggestion:\n"
        "  title, description (what to automate), confidence (0.7-1.0), action_id, context."
    )

    text = _call_claude_sync(prompt, "Analyze for patterns.")
    suggestions = _parse_suggestions(text)

    for s in suggestions:
        s["source"] = "pattern"

    if suggestions:
        print(f"[suggestion_engine] Pattern detected: {suggestions[0]['title']}")
    return suggestions


def load_rewards() -> list[dict]:
    """Load reward history from disk."""
    if not REWARDS_PATH.exists():
        return []
    rewards = []
    try:
        with open(REWARDS_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    rewards.append(json.loads(line))
    except (IOError, json.JSONDecodeError):
        pass
    return rewards


def _fetch_screenshot() -> str | None:
    """Fetch the latest desktop screenshot from the agent server as base64 JPEG."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request("http://localhost:8421/screenshot", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("image")
    except Exception as e:
        print(f"[suggestion_engine] Screenshot fetch failed: {e}")
        return None


def ambient_tick(
    conversation_history: list[dict],
    profile: dict | None = None,
) -> list[dict]:
    """
    Layer 3: Ambient awareness tick. Called every 30s by the orchestrator.
    Fetches a screenshot of the twin's desktop and combines it with
    conversation history, profile, and reward history for a multimodal LLM call.
    Returns a list of suggestion dicts (usually 0 or 1).
    """
    screenshot_b64 = _fetch_screenshot()

    # Build context
    profile_summary = ""
    if profile:
        profile_summary = (
            f"User: {profile.get('name', '')}, "
            f"{profile.get('title', '')} at {profile.get('company', '')}. "
            f"Interests: {', '.join(profile.get('interests', []))}."
        )

    recent_messages = []
    for m in conversation_history[-10:]:
        role = m.get("role", "unknown")
        content = m.get("content", "")[:200]
        recent_messages.append(f"  [{role}]: {content}")
    conversation_text = "\n".join(recent_messages) if recent_messages else "(no conversation yet)"

    rewards = load_rewards()
    reward_summary = ""
    if rewards:
        accepted = sum(1 for r in rewards if r.get("action") == "accept")
        dismissed = sum(1 for r in rewards if r.get("action") == "dismiss")
        reward_summary = f"Past suggestions: {accepted} accepted, {dismissed} dismissed."

    prompt = (
        "You are a proactive digital twin running on a separate macOS desktop.\n"
        "You are always watching and thinking about how to help.\n\n"
        f"User profile: {profile_summary}\n\n"
        f"Conversation history:\n{conversation_text}\n\n"
        f"{reward_summary}\n\n"
    )

    if screenshot_b64:
        prompt += (
            "Above is a screenshot of your desktop. Based on what you see, "
            "what you know about the user, and the conversation so far, "
            "is there something proactive you should suggest?\n\n"
        )
    else:
        prompt += (
            "You don't have a screenshot right now. Based on the user's profile "
            "and conversation history, is there something proactive you should suggest?\n\n"
        )

    prompt += (
        "Only suggest if confidence > 0.7. If nothing valuable to suggest, "
        "return {\"suggestions\": []}.\n"
        "If you have a suggestion, return a JSON object with a 'suggestions' array "
        "containing ONE suggestion: title, description, confidence, action_id, context."
    )

    # Build user content (with optional image for multimodal via Anthropic vision)
    if screenshot_b64:
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": screenshot_b64}},
            {"type": "text", "text": "Analyze my desktop and suggest something proactive."},
        ]
    else:
        user_content = "Suggest something proactive based on the context above."

    text = _call_claude_sync(prompt, user_content)
    suggestions = _parse_suggestions(text)

    for s in suggestions:
        s["source"] = "ambient"

    if suggestions:
        print(f"[suggestion_engine] Ambient suggestion: {suggestions[0]['title']}")
    return suggestions
