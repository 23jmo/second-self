"""Hex-powered habit analyzer — two-subagent pipeline.

Subagent 1 (Query Agent): connects to Hex via MCP, runs an analysis thread
on the user's Firestore data (automation runs, session timing, signals).

Subagent 2 (Pattern Extractor): takes the raw Hex output and extracts a
structured JSON of habit patterns used downstream for RL tuning.

Firestore output: users/{user_id}/habit_analysis/latest
"""

import json
import logging
import os
from typing import Any

import anthropic
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")

_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
_HEX_MCP_URL = "https://app.hex.tech/mcp"

# ---------------------------------------------------------------------------
# Subagent system prompts
# ---------------------------------------------------------------------------

_QUERY_SYSTEM_PROMPT = """\
You are a data-analysis agent connected to Hex via the Hex MCP tool.

Your task:
1. Create a Thread in Hex with this analysis request:
   "Analyse this user's automation run history, session activity timing, \
and interaction signals. Find: peak activity hours, most accepted \
automation types, days with highest engagement, any automations that \
haven't run in 7+ days, and gaps where automations could help."
2. Pass the user's Firestore collection path as context so Hex can query it.
3. Return the FULL raw Hex Thread response — do not summarise or filter it.

Firestore collection path: {firestore_path}
User context: {user_context}

Use the create_thread tool to start the Hex analysis. Return the complete
response content from Hex."""

_PATTERN_SYSTEM_PROMPT = """\
You are a structured-data extraction agent. You receive raw analytical output
from a Hex data analysis thread and must extract habit patterns into JSON.

Return ONLY a valid JSON object with exactly these keys — no preamble, no
markdown fences, no explanation:

{{
  "peak_hours": [int],        // hours 0-23 when user is most active
  "peak_days": [str],         // day names e.g. ["Monday", "Wednesday"]
  "top_automation_types": [str],  // most accepted automation categories
  "stale_automations": [str],     // automation IDs not run in 7+ days
  "suggested_gaps": [str],        // plain-English descriptions of missing automations
  "confidence": float             // 0.0 to 1.0 based on data quality
}}

Rules:
- peak_hours must be integers 0-23, sorted ascending
- peak_days must be English day names, title-cased
- confidence should be lower if the source data is sparse or ambiguous
- If a field cannot be determined, use an empty list or 0.0
- Return ONLY the JSON object"""


# ---------------------------------------------------------------------------
# Hex MCP tool definition (passed to the Query subagent)
# ---------------------------------------------------------------------------

_HEX_TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_thread",
        "description": (
            "Create a new analysis thread in Hex. Sends a query to the Hex "
            "MCP server and returns the analytical response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The analysis question to send to Hex.",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context such as Firestore paths.",
                },
            },
            "required": ["query"],
        },
    }
]


# ---------------------------------------------------------------------------
# MCP bridge — forwards tool calls to Hex
# ---------------------------------------------------------------------------

async def _call_hex_mcp(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Forward a tool call to the Hex MCP server and return the response text."""
    import httpx

    hex_token = os.getenv("HEX_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if hex_token:
        headers["Authorization"] = f"Bearer {hex_token}"

    payload = {
        "method": "tools/call",
        "params": {"name": tool_name, **tool_input},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(_HEX_MCP_URL, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    # MCP responses nest content under result.content
    content = body.get("result", {}).get("content", [])
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(texts) if texts else json.dumps(body)


# ---------------------------------------------------------------------------
# Subagent runners
# ---------------------------------------------------------------------------

async def _run_query_agent(user_id: str, user_context: dict[str, Any]) -> str:
    """Subagent 1: query Hex for habit analysis via MCP tool use."""
    client = anthropic.AsyncAnthropic()
    firestore_path = f"users/{user_id}"

    system = _QUERY_SYSTEM_PROMPT.format(
        firestore_path=firestore_path,
        user_context=json.dumps(user_context, default=str),
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Run the Hex analysis now."},
    ]

    # Tool-use loop — max 4 turns
    for _ in range(4):
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=system,
            tools=_HEX_TOOLS,
            messages=messages,
        )

        # Collect text and tool-use blocks
        assistant_content = []
        text_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            return "\n".join(text_parts)

        # Handle tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log.info("Hex query agent calling tool: %s", block.name)
                try:
                    result_text = await _call_hex_mcp(block.name, block.input)
                except Exception as exc:
                    log.error("Hex MCP call failed: %s", exc)
                    result_text = f"Error calling Hex: {exc}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

        messages.append({"role": "user", "content": tool_results})

    return "\n".join(text_parts) if text_parts else "No response from Hex"


async def _run_pattern_agent(raw_hex_output: str) -> dict[str, Any]:
    """Subagent 2: extract structured patterns from raw Hex output."""
    client = anthropic.AsyncAnthropic()

    response = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_PATTERN_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Extract patterns from this Hex analysis:\n\n{raw_hex_output}"},
        ],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    # Strip markdown fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        patterns = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error("Pattern agent returned invalid JSON: %s", exc)
        raise ValueError(f"Pattern extraction failed — invalid JSON: {exc}") from exc

    return _validate_patterns(patterns)


def _validate_patterns(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise and validate the pattern dict from the extractor."""
    valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

    peak_hours = [h for h in raw.get("peak_hours", []) if isinstance(h, int) and 0 <= h <= 23]
    peak_days = [d for d in raw.get("peak_days", []) if d in valid_days]
    top_types = [t for t in raw.get("top_automation_types", []) if isinstance(t, str)]
    stale = [s for s in raw.get("stale_automations", []) if isinstance(s, str)]
    gaps = [g for g in raw.get("suggested_gaps", []) if isinstance(g, str)]

    confidence = raw.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    return {
        "peak_hours": sorted(peak_hours),
        "peak_days": peak_days,
        "top_automation_types": top_types,
        "stale_automations": stale,
        "suggested_gaps": gaps,
        "confidence": round(confidence, 2),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_habits(user_id: str, user_context: dict[str, Any]) -> dict[str, Any]:
    """Run the full two-subagent Hex analysis pipeline.

    1. Query Agent → raw Hex analysis
    2. Pattern Agent → structured habit dict

    Saves the result to Firestore and returns it.
    """
    log.info("Starting Hex habit analysis for user %s", user_id[:12])
    print(f"[hex_analyzer] starting analysis for user={user_id[:12]}")

    # Subagent 1: Query Hex
    raw_output = await _run_query_agent(user_id, user_context)
    print(f"[hex_analyzer] query agent returned {len(raw_output)} chars")
    log.info("Query agent returned %d chars", len(raw_output))

    # Subagent 2: Extract patterns
    patterns = await _run_pattern_agent(raw_output)
    print(f"[hex_analyzer] extracted patterns: confidence={patterns['confidence']}")
    log.info("Pattern extraction complete: confidence=%.2f", patterns["confidence"])

    # Persist to Firestore
    db = get_db()
    if db is not None:
        doc = {
            **patterns,
            "user_id": user_id,
            "raw_hex_output": raw_output[:10000],  # cap storage
            "updated_at": SERVER_TIMESTAMP,
        }
        db.collection("users").document(user_id).collection(
            "habit_analysis"
        ).document("latest").set(doc)
        print(f"[hex_analyzer] saved to Firestore users/{user_id[:12]}/habit_analysis/latest")
    else:
        log.warning("Firestore unavailable — habit analysis not persisted")

    return patterns


# ---------------------------------------------------------------------------
# CLI smoke test — uses mock Hex output to test the pattern extractor
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from dotenv import load_dotenv

    load_dotenv()

    _MOCK_HEX_OUTPUT = """\
## User Activity Analysis

### Peak Activity
The user is most active between 9-11 AM and 2-4 PM on weekdays.
Monday and Wednesday show the highest engagement (35% of all sessions).

### Automation Performance
- "automation" type: 78% acceptance rate (top performer)
- "content" type: 62% acceptance rate
- "timing" type: 45% acceptance rate
- "habit" type: 31% acceptance rate

### Stale Automations
The following automations have not executed in the past 7+ days:
- auto_weekly_digest_abc123
- auto_friday_recap_def456

### Suggested Gaps
1. No morning briefing automation — user checks email manually every day at 9 AM
2. No end-of-week summary — user manually compiles notes every Friday
3. No meeting-prep automation — user has 5+ meetings/week with no pre-read

### Data Quality
Based on 142 resolved signals and 89 automation runs over the past 30 days.
Confidence: HIGH
"""

    async def _smoke_test():
        print("=== Testing pattern extractor with mock Hex output ===\n")
        patterns = await _run_pattern_agent(_MOCK_HEX_OUTPUT)
        print(json.dumps(patterns, indent=2))

        print("\n=== Validating output structure ===")
        assert isinstance(patterns["peak_hours"], list)
        assert isinstance(patterns["peak_days"], list)
        assert isinstance(patterns["top_automation_types"], list)
        assert isinstance(patterns["stale_automations"], list)
        assert isinstance(patterns["suggested_gaps"], list)
        assert 0.0 <= patterns["confidence"] <= 1.0
        print("All assertions passed.")

    asyncio.run(_smoke_test())
