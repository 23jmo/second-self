"""Tool definitions and dispatch for the Anthropic Messages API.

Defines tools in the format expected by `client.messages.create(tools=...)`,
and routes tool calls to the implementation functions in tools.py.
"""

import asyncio
import base64
import logging
from email.mime.text import MIMEText
from typing import Any

from src.connectors.tavily import search_user

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Scheduler reference (set by server lifespan)
# ---------------------------------------------------------------------------

_scheduler_ref = None


def set_scheduler_ref(scheduler) -> None:
    """Store a reference to the BackgroundScheduler for live job registration."""
    global _scheduler_ref
    _scheduler_ref = scheduler


def _get_scheduler():
    return _scheduler_ref

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic Messages API format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "send_email",
        "description": (
            "Send a new email on behalf of the user. Write the body in their voice and style. "
            "Only call this after the user has confirmed a draft, or if they explicitly said to send directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text, written in the user's voice"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Draft an email for the user to review before sending. Shows the formatted email "
            "and asks for confirmation. Use this BEFORE send_email unless the user explicitly "
            "said to send directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text, written in the user's voice"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "reply_to_email",
        "description": (
            "Reply to an existing email thread. Use read_emails first to find the message_id "
            "and thread_id. Write the reply in the user's voice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID (from read_emails)"},
                "thread_id": {"type": "string", "description": "Gmail thread ID (from read_emails)"},
                "body": {"type": "string", "description": "Reply body text, in the user's voice"},
            },
            "required": ["message_id", "thread_id", "body"],
        },
    },
    {
        "name": "read_emails",
        "description": (
            "Search and read the user's emails. Returns message IDs and thread IDs for "
            "reply_to_email. Supports Gmail search syntax."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "limit": {"type": "integer", "description": "Max emails to return (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_contact_info",
        "description": (
            "Look up a contact's email address by searching recent emails for their name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The person's name to search for"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "summarize_emails",
        "description": (
            "Read and summarize a batch of emails. Use when the user asks for an overview "
            "of their inbox, unread emails, or emails from a specific sender/topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "limit": {"type": "integer", "description": "Max emails to summarize (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_event",
        "description": "Create a new Google Calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time in ISO 8601"},
                "end": {"type": "string", "description": "End time in ISO 8601"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Attendee email addresses",
                },
                "description": {"type": "string", "description": "Event description/notes"},
                "location": {"type": "string", "description": "Event location"},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "update_event",
        "description": "Update an existing Google Calendar event. Only provide fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Calendar event ID"},
                "title": {"type": "string", "description": "New event title"},
                "start": {"type": "string", "description": "New start time in ISO 8601"},
                "end": {"type": "string", "description": "New end time in ISO 8601"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Updated attendee emails",
                },
                "description": {"type": "string", "description": "New event description"},
                "location": {"type": "string", "description": "New event location"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete/cancel a Google Calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to delete"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "list_events",
        "description": "List upcoming Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Days to look ahead (default 7)"},
                "query": {"type": "string", "description": "Text search to filter events"},
            },
        },
    },
    {
        "name": "create_document",
        "description": "Create a new Google Doc. Returns the document URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "body_text": {"type": "string", "description": "Initial body content (plain text)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_presentation",
        "description": "Create a new Google Slides presentation. Returns the presentation URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Presentation title"},
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                        },
                    },
                    "description": "List of slides with title and body",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "share_document",
        "description": "Share a Google Doc/Slides/Drive file with someone by email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID"},
                "email": {"type": "string", "description": "Recipient email"},
                "role": {
                    "type": "string",
                    "enum": ["reader", "commenter", "writer"],
                    "description": "Permission level (default: writer)",
                },
                "notify": {"type": "boolean", "description": "Send notification (default: true)"},
            },
            "required": ["file_id", "email"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web for information using Tavily.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_automation",
        "description": (
            "Create a recurring automation for the user. Use when they ask to schedule "
            "something to happen regularly (e.g. 'every Monday email the team a standup', "
            "'at 5pm daily summarize my emails'). Parses the request into a structured spec "
            "and saves it. Returns a confirmation message or a clarifying question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_request": {
                    "type": "string",
                    "description": "The user's natural language automation request, exactly as they phrased it",
                },
            },
            "required": ["user_request"],
        },
    },
    {
        "name": "manage_automations",
        "description": (
            "Manage the user's existing automations: pause, resume, edit, delete, or run "
            "one immediately. Use when they ask to change, stop, restart, test, or remove "
            "an automation. Also use for 'run my standup now' or 'fire that automation'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_request": {
                    "type": "string",
                    "description": "The user's natural language management request",
                },
            },
            "required": ["user_request"],
        },
    },
    {
        "name": "list_automations",
        "description": (
            "List all of the user's automations with their status, schedule, and run count. "
            "Use when the user asks 'what automations do I have', 'show my scheduled tasks', "
            "or 'list my recurring actions'. This is a fast read-only operation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_automation",
        "description": (
            "Run a saved automation immediately by name. Use when the user types "
            "'/automation [name]' or asks to 'run [automation name] now'. Looks up the "
            "automation by name and executes it on the spot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name or partial name of the automation to run",
                },
            },
            "required": ["name"],
        },
    },
]


# ---------------------------------------------------------------------------
# Google service builders
# ---------------------------------------------------------------------------

def _build_gmail_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds)


def _build_calendar_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("calendar", "v3", credentials=creds)


def _build_docs_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("docs", "v1", credentials=creds)


def _build_slides_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("slides", "v1", credentials=creds)


def _build_drive_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


def _require_token(access_token: str | None) -> str:
    if not access_token:
        raise ValueError("No Google authentication. Sign in first to use this tool.")
    return access_token


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

async def dispatch_tool(
    name: str,
    args: dict[str, Any],
    access_token: str | None,
    uid: str = "",
) -> str:
    """Execute a tool by name and return a string result."""

    # --- Automation tools (no Google token needed) ---
    if name == "create_automation":
        return await _create_automation_handler(uid, args.get("user_request", ""))

    if name == "manage_automations":
        return await _manage_automations_handler(uid, args.get("user_request", ""))

    if name == "list_automations":
        return _list_automations_handler(uid)

    if name == "run_automation":
        return await _run_automation_handler(uid, args.get("name", ""), access_token)

    if name == "search_web":
        return await search_user(args["query"])

    if name == "draft_email":
        return (
            f"--- DRAFT EMAIL ---\n"
            f"To: {args['to']}\n"
            f"Subject: {args['subject']}\n\n"
            f"{args['body']}\n"
            f"--- END DRAFT ---"
        )

    # All other tools require Google auth
    token = _require_token(access_token)

    if name == "send_email":
        return await _send_email(token, args["to"], args["subject"], args["body"])
    elif name == "reply_to_email":
        return await _reply_to_email(token, args["message_id"], args["thread_id"], args["body"])
    elif name == "read_emails":
        return await _read_emails(token, args["query"], args.get("limit", 5))
    elif name == "get_contact_info":
        return await _search_contacts(token, args["name"])
    elif name == "summarize_emails":
        return await _read_emails_with_bodies(token, args["query"], args.get("limit", 10))
    elif name == "create_event":
        return await _create_event(
            token, args["title"], args["start"], args["end"],
            attendees=args.get("attendees"), description=args.get("description", ""),
            location=args.get("location", ""),
        )
    elif name == "update_event":
        return await _update_event(
            token, args["event_id"], title=args.get("title"),
            start=args.get("start"), end=args.get("end"),
            attendees=args.get("attendees"), description=args.get("description"),
            location=args.get("location"),
        )
    elif name == "delete_event":
        return await _delete_event(token, args["event_id"])
    elif name == "list_events":
        return await _list_events(token, args.get("days_ahead", 7), args.get("query", ""))
    elif name == "create_document":
        result = await _create_document(token, args["title"], args.get("body_text", ""))
        return f"Created Google Doc: '{result['title']}'\nDocument ID: {result['document_id']}\nURL: {result['url']}"
    elif name == "create_presentation":
        result = await _create_presentation(token, args["title"], args.get("slides"))
        return f"Created Google Slides: '{result['title']}'\nPresentation ID: {result['presentation_id']}\nURL: {result['url']}"
    elif name == "share_document":
        return await _share_document(
            token, args["file_id"], args["email"],
            role=args.get("role", "writer"), notify=args.get("notify", True),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Implementation functions (moved from tools.py)
# ---------------------------------------------------------------------------

async def _send_email(access_token: str, to: str, subject: str, body: str) -> str:
    def _send():
        service = _build_gmail_service(access_token)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email sent to {to} with subject '{subject}'"
    return await asyncio.to_thread(_send)


async def _reply_to_email(access_token: str, message_id: str, thread_id: str, body: str) -> str:
    def _reply():
        service = _build_gmail_service(access_token)
        original = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["Subject", "From", "To", "Message-ID"],
        ).execute()
        headers = {h["name"]: h["value"] for h in original["payload"].get("headers", [])}
        reply_to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message = MIMEText(body)
        message["to"] = reply_to
        message["subject"] = subject
        message["In-Reply-To"] = headers.get("Message-ID", "")
        message["References"] = headers.get("Message-ID", "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": thread_id}
        ).execute()
        return f"Reply sent to {reply_to} in thread '{subject}'"
    return await asyncio.to_thread(_reply)


async def _read_emails(access_token: str, query: str, limit: int = 5) -> str:
    def _read():
        service = _build_gmail_service(access_token)
        results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        emails = []
        for msg in results.get("messages", []):
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}
            snippet = full.get("snippet", "")
            emails.append(
                f"Message ID: {msg['id']}\nThread ID: {full.get('threadId', '')}\n"
                f"From: {headers.get('From', '?')}\nTo: {headers.get('To', '?')}\n"
                f"Subject: {headers.get('Subject', '?')}\nDate: {headers.get('Date', '?')}\n"
                f"Preview: {snippet}"
            )
        if not emails:
            return "No emails found matching that query."
        return "\n\n---\n\n".join(emails)
    return await asyncio.to_thread(_read)


async def _read_emails_with_bodies(access_token: str, query: str, limit: int = 10) -> str:
    def _read():
        service = _build_gmail_service(access_token)
        results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        emails = []
        for msg in results.get("messages", []):
            full = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}
            body_text = ""
            payload = full.get("payload", {})
            if "parts" in payload:
                for part in payload["parts"]:
                    if part.get("mimeType") == "text/plain":
                        data = part.get("body", {}).get("data", "")
                        if data:
                            body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                            break
            elif payload.get("body", {}).get("data"):
                body_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            if len(body_text) > 500:
                body_text = body_text[:500] + "..."
            emails.append(
                f"From: {headers.get('From', '?')}\nTo: {headers.get('To', '?')}\n"
                f"Subject: {headers.get('Subject', '?')}\nDate: {headers.get('Date', '?')}\n"
                f"Body:\n{body_text}"
            )
        if not emails:
            return "No emails found matching that query."
        return "\n\n===\n\n".join(emails)
    return await asyncio.to_thread(_read)


async def _search_contacts(access_token: str, name: str) -> str:
    def _search():
        service = _build_gmail_service(access_token)
        found_emails = set()
        for q in [f"from:{name}", f"to:{name}"]:
            results = service.users().messages().list(userId="me", q=q, maxResults=10).execute()
            for msg in results.get("messages", []):
                full = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From", "To"],
                ).execute()
                headers = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}
                for field in ["From", "To"]:
                    val = headers.get(field, "")
                    if name.lower() in val.lower():
                        found_emails.add(val)
        if not found_emails:
            return f"No email addresses found for '{name}'."
        return f"Found contacts matching '{name}':\n" + "\n".join(sorted(found_emails))
    return await asyncio.to_thread(_search)


async def _create_event(
    access_token: str, title: str, start: str, end: str,
    attendees: list[str] | None = None, description: str = "", location: str = "",
) -> str:
    def _create():
        service = _build_calendar_service(access_token)
        event: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if attendees:
            event["attendees"] = [{"email": e} for e in attendees]
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        created = service.events().insert(calendarId="primary", body=event).execute()
        return f"Event '{title}' created: {created.get('htmlLink', '')}"
    return await asyncio.to_thread(_create)


async def _update_event(
    access_token: str, event_id: str, title: str | None = None,
    start: str | None = None, end: str | None = None,
    attendees: list[str] | None = None, description: str | None = None,
    location: str | None = None,
) -> str:
    def _update():
        service = _build_calendar_service(access_token)
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()
        if title is not None:
            existing["summary"] = title
        if start is not None:
            existing["start"] = {"dateTime": start}
        if end is not None:
            existing["end"] = {"dateTime": end}
        if attendees is not None:
            existing["attendees"] = [{"email": e} for e in attendees]
        if description is not None:
            existing["description"] = description
        if location is not None:
            existing["location"] = location
        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=existing
        ).execute()
        return f"Event '{updated.get('summary', '')}' updated: {updated.get('htmlLink', '')}"
    return await asyncio.to_thread(_update)


async def _delete_event(access_token: str, event_id: str) -> str:
    def _delete():
        service = _build_calendar_service(access_token)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"Event {event_id} deleted."
    return await asyncio.to_thread(_delete)


async def _list_events(access_token: str, days_ahead: int = 7, query: str = "") -> str:
    def _list():
        from datetime import datetime, timedelta, timezone
        service = _build_calendar_service(access_token)
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)
        params: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 20,
        }
        if query:
            params["q"] = query
        results = service.events().list(**params).execute()
        events = results.get("items", [])
        if not events:
            return f"No events found in the next {days_ahead} days."
        lines = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", "?"))
            end = e["end"].get("dateTime", e["end"].get("date", "?"))
            attendee_count = len(e.get("attendees", []))
            lines.append(
                f"Event ID: {e['id']}\nTitle: {e.get('summary', '(no title)')}\n"
                f"Start: {start}\nEnd: {end}\n"
                f"Location: {e.get('location', 'N/A')}\nAttendees: {attendee_count}"
            )
        return "\n\n---\n\n".join(lines)
    return await asyncio.to_thread(_list)


async def _create_document(access_token: str, title: str, body_text: str = "") -> dict:
    def _create():
        docs = _build_docs_service(access_token)
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        if body_text:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": body_text}}]},
            ).execute()
        return {"document_id": doc_id, "title": title, "url": f"https://docs.google.com/document/d/{doc_id}/edit"}
    return await asyncio.to_thread(_create)


async def _create_presentation(access_token: str, title: str, slides: list[dict] | None = None) -> dict:
    def _create():
        svc = _build_slides_service(access_token)
        pres = svc.presentations().create(body={"title": title}).execute()
        pres_id = pres["presentationId"]
        if slides:
            requests = []
            for i in range(1, len(slides)):
                requests.append({"createSlide": {"insertionIndex": i}})
            if requests:
                svc.presentations().batchUpdate(presentationId=pres_id, body={"requests": requests}).execute()
            pres = svc.presentations().get(presentationId=pres_id).execute()
            page_ids = [s["objectId"] for s in pres.get("slides", [])]
            text_requests = []
            for i, slide_data in enumerate(slides):
                if i >= len(page_ids):
                    break
                slide_obj = pres["slides"][i]
                for element in slide_obj.get("pageElements", []):
                    shape = element.get("shape", {})
                    ph = shape.get("placeholder", {})
                    ph_type = ph.get("type", "")
                    obj_id = element["objectId"]
                    if ph_type in ("TITLE", "CENTERED_TITLE") and slide_data.get("title"):
                        text_requests.append({"insertText": {"objectId": obj_id, "text": slide_data["title"], "insertionIndex": 0}})
                    elif ph_type in ("BODY", "SUBTITLE") and slide_data.get("body"):
                        text_requests.append({"insertText": {"objectId": obj_id, "text": slide_data["body"], "insertionIndex": 0}})
            if text_requests:
                svc.presentations().batchUpdate(presentationId=pres_id, body={"requests": text_requests}).execute()
        return {
            "presentation_id": pres_id,
            "title": title,
            "url": f"https://docs.google.com/presentation/d/{pres_id}/edit",
            "slide_count": len(slides) if slides else 1,
        }
    return await asyncio.to_thread(_create)


async def _share_document(
    access_token: str, file_id: str, email: str,
    role: str = "writer", notify: bool = True,
) -> str:
    def _share():
        drive = _build_drive_service(access_token)
        drive.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=notify,
        ).execute()
        file_meta = drive.files().get(fileId=file_id, fields="name,webViewLink").execute()
        return f"Shared '{file_meta.get('name', file_id)}' with {email} as {role}. Link: {file_meta.get('webViewLink', '')}"
    return await asyncio.to_thread(_share)


# ---------------------------------------------------------------------------
# Automation tool handlers
# ---------------------------------------------------------------------------

async def _create_automation_handler(uid: str, user_request: str) -> str:
    """Parse and save a new automation from natural language."""
    if not uid:
        return "Error: You must be signed in to create automations."

    from agents.automation_parser import parse_automation
    from utils.automation_store import save_automation
    from utils.firebase_context import load_user_context

    user_context = load_user_context(uid)
    spec = await parse_automation(user_request, user_context)

    if spec.get("clarification_needed"):
        return spec["clarification_needed"]

    try:
        auto_id = save_automation(uid, spec, source_message=user_request)
    except (RuntimeError, ValueError) as exc:
        return f"Error saving automation: {exc}"

    # Register with scheduler if running
    try:
        from daemons.automation_scheduler import register_automation
        scheduler = _get_scheduler()
        if scheduler:
            spec_with_id = {**spec, "id": auto_id, "enabled": True}
            register_automation(scheduler, uid, spec_with_id, user_context)
    except Exception as exc:
        log.warning("Scheduler registration failed for %s: %s", auto_id, exc)

    confirmation = spec.get("confirmation_message", f"Automation '{spec.get('name')}' created.")
    trigger = spec.get("trigger", {})
    schedule_str = trigger.get("human_readable", trigger.get("cron", ""))
    return f"{confirmation}\n\nAutomation ID: {auto_id}\nSchedule: {schedule_str}"


async def _manage_automations_handler(uid: str, user_request: str) -> str:
    """Route management requests to the automation manager."""
    if not uid:
        return "Error: You must be signed in to manage automations."

    from agents.automation_manager import handle_manage_request, set_scheduler
    from utils.firebase_context import load_user_context

    scheduler = _get_scheduler()
    if scheduler:
        set_scheduler(scheduler)

    user_context = load_user_context(uid)
    return await handle_manage_request(uid, user_request, user_context)


def _list_automations_handler(uid: str) -> str:
    """List all automations for the user (no LLM call)."""
    if not uid:
        return "Error: You must be signed in to view automations."

    from utils.automation_store import get_all_automations

    automations = get_all_automations(uid, enabled_only=False)
    if not automations:
        return "You don't have any automations set up yet. Ask me to create one!"

    lines = [f"You have {len(automations)} automation(s):\n"]
    for a in automations:
        trigger = a.get("trigger", {})
        action = a.get("action", {})
        status = "active" if a.get("enabled") else "paused"
        schedule = trigger.get("human_readable") or trigger.get("cron", "?")
        fn = action.get("function", "?")
        to = action.get("params", {}).get("to", "")
        to_str = f" -> {to}" if to else ""
        runs = a.get("run_count", 0)
        lines.append(
            f"  {a.get('id')} | {a.get('name')} [{status}]\n"
            f"    Schedule: {schedule} | Action: {fn}{to_str} | Runs: {runs}"
        )
    return "\n".join(lines)


async def _run_automation_handler(uid: str, name_query: str, access_token: str | None) -> str:
    """Look up an automation by name and execute it immediately."""
    if not uid:
        return "Error: You must be signed in to run automations."

    if not name_query:
        return "Error: Please provide the name of the automation to run."

    from utils.automation_store import find_by_name
    from utils.firebase_context import load_user_context
    from agents.automation_executor import execute_automation

    matches = find_by_name(uid, name_query)
    if not matches:
        return f"No automation found matching '{name_query}'. Use list_automations to see your automations."

    if len(matches) > 1:
        names = ", ".join(f"'{m.get('name')}'" for m in matches[:5])
        return f"Multiple automations match '{name_query}': {names}. Please be more specific."

    auto = matches[0]
    auto_id = auto.get("id", "")
    auto_name = auto.get("name", auto_id)

    user_context = load_user_context(uid)
    log.info("Running automation '%s' (%s) on demand", auto_name, auto_id)

    result = await execute_automation(uid, auto_id, user_context)

    status = result.get("status", "unknown")
    summary = result.get("summary", "")
    error = result.get("error")

    if status == "error":
        return f"Automation '{auto_name}' failed: {error or summary}"

    return f"Ran '{auto_name}' — {summary[:300] if summary else status}"
