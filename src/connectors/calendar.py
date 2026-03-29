"""Google Calendar connector.

Tells you how someone structures their time — meeting load, work hours,
what they prioritize.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.models.schemas import CalendarEvent


def _fetch_calendar_events(access_token: str) -> list[CalendarEvent]:
    """Synchronous Calendar API calls (run in thread pool)."""
    creds = Credentials(token=access_token)
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc).isoformat()
    two_weeks = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            timeMax=two_weeks,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for e in events_result.get("items", []):
        events.append(
            CalendarEvent(
                title=e.get("summary", "(no title)"),
                start=e["start"].get("dateTime", e["start"].get("date", "")),
                recurring="recurrence" in e,
                attendee_count=len(e.get("attendees", [])),
            )
        )

    return events


async def get_calendar_events(access_token: str) -> list[CalendarEvent]:
    """Async wrapper — runs Calendar API calls in a thread pool."""
    return await asyncio.to_thread(_fetch_calendar_events, access_token)
