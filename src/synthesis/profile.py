"""Claude synthesis — raw data becomes a second self.

Takes emails, calendar events, and Tavily results, feeds them into
one Claude call, and outputs a structured SecondSelfProfile.
"""

import json
import os

import anthropic

from src.models.schemas import (
    CalendarEvent,
    EmailMessage,
    SecondSelfProfile,
)

SYNTHESIS_PROMPT = """\
You are building a digital twin profile for an AI agent that will act on this person's behalf.
Analyze their data carefully. Return ONLY valid JSON, nothing else.

SENT EMAILS (up to 50):
{emails_text}

CALENDAR (next 2 weeks):
{calendar_text}

PUBLIC INFO:
{tavily_results}

Return this exact JSON structure:
{{
  "identity": {{
    "name": "",
    "role": "",
    "company": ""
  }},
  "voice": {{
    "formality": "casual|professional|casual-professional",
    "avg_email_length": "short|medium|long",
    "signature_phrases": [],
    "opens_with": "",
    "closes_with": "",
    "tone": ""
  }},
  "behavior": {{
    "work_hours": "",
    "meeting_load": "light|medium|heavy",
    "response_style": "",
    "peak_focus_time": ""
  }},
  "context": {{
    "active_projects": [],
    "top_collaborators": [],
    "current_priorities": []
  }}
}}
"""


async def build_second_self(
    emails: list[EmailMessage],
    calendar_events: list[CalendarEvent],
    tavily_results: str,
) -> SecondSelfProfile:
    """Synthesize a second-self profile from all collected data."""
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    emails_text = "\n\n".join(
        f"To: {e.to}\nSubject: {e.subject}\n{e.body}" for e in emails[:50]
    )
    if not emails_text:
        emails_text = "(no email data available)"

    calendar_text = "\n".join(
        f"- {e.title} | {e.start} | {e.attendee_count} attendees | recurring: {e.recurring}"
        for e in calendar_events
    )
    if not calendar_text:
        calendar_text = "(no calendar data available)"

    if not tavily_results:
        tavily_results = "(no public info available)"

    prompt = SYNTHESIS_PROMPT.format(
        emails_text=emails_text,
        calendar_text=calendar_text,
        tavily_results=tavily_results,
    )

    client = anthropic.AsyncAnthropic()

    response = await client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]  # remove first line
        raw = raw.rsplit("```", 1)[0]  # remove closing fence

    profile_data = json.loads(raw)
    return SecondSelfProfile(**profile_data)
