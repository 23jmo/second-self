"""Gemini synthesis — raw data becomes a second self.

Takes emails, calendar events, and Tavily results, feeds them into
one Gemini call, and outputs a structured SecondSelfProfile.
"""

import json

from src.models.schemas import (
    CalendarEvent,
    EmailMessage,
    SecondSelfProfile,
)
from src.synthesis.gemini_client import call_gemini_async, _strip_json_fences

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

    raw = await call_gemini_async(prompt, max_tokens=1500, temperature=0)
    raw = _strip_json_fences(raw)

    profile_data = json.loads(raw)
    return SecondSelfProfile(**profile_data)
