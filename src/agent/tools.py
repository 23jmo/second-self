"""Tool definitions for the chat agent — Claude Agent SDK version.

Uses a closure factory pattern so that the Google OAuth access_token
is captured per-request without globals or thread-locals.

Tools: send_email, reply_to_email, read_emails, draft_email,
get_contact_info, summarize_emails, create_event, update_event,
delete_event, list_events, create_document, create_presentation,
share_document, search_web.
"""

import asyncio
import base64
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from claude_agent_sdk import tool, create_sdk_mcp_server, ToolAnnotations
from src.connectors.tavily import search_user


# --- Service builders ---

def _build_gmail_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds)


def _build_calendar_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("calendar", "v3", credentials=creds)


def _build_docs_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("docs", "v1", credentials=creds)


def _build_slides_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("slides", "v1", credentials=creds)


def _build_drive_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


# --- Email implementation functions ---

async def _send_email(access_token: str, to: str, subject: str, body: str) -> str:
    def _send():
        service = _build_gmail_service(access_token)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
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
        results = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
        emails = []
        for msg in results.get("messages", []):
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}
            snippet = full.get("snippet", "")
            emails.append(
                f"Message ID: {msg['id']}\n"
                f"Thread ID: {full.get('threadId', '')}\n"
                f"From: {headers.get('From', '?')}\n"
                f"To: {headers.get('To', '?')}\n"
                f"Subject: {headers.get('Subject', '?')}\n"
                f"Date: {headers.get('Date', '?')}\n"
                f"Preview: {snippet}"
            )
        if not emails:
            return "No emails found matching that query."
        return "\n\n---\n\n".join(emails)
    return await asyncio.to_thread(_read)


async def _read_emails_with_bodies(access_token: str, query: str, limit: int = 10) -> str:
    """Read emails with full body text (truncated) for summarization."""
    def _read():
        service = _build_gmail_service(access_token)
        results = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
        emails = []
        for msg in results.get("messages", []):
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="full",
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}

            # Extract body text
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

            # Truncate long bodies
            if len(body_text) > 500:
                body_text = body_text[:500] + "..."

            emails.append(
                f"From: {headers.get('From', '?')}\n"
                f"To: {headers.get('To', '?')}\n"
                f"Subject: {headers.get('Subject', '?')}\n"
                f"Date: {headers.get('Date', '?')}\n"
                f"Body:\n{body_text}"
            )
        if not emails:
            return "No emails found matching that query."
        return "\n\n===\n\n".join(emails)
    return await asyncio.to_thread(_read)


async def _search_contacts(access_token: str, name: str) -> str:
    """Search Gmail for a person's email address by name."""
    def _search():
        service = _build_gmail_service(access_token)
        # Search both sent and received emails for this name
        found_emails = set()
        for q in [f"from:{name}", f"to:{name}"]:
            results = service.users().messages().list(
                userId="me", q=q, maxResults=10
            ).execute()
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
            return f"No email addresses found for '{name}'. Try searching with a different name or ask the user."
        return f"Found contacts matching '{name}':\n" + "\n".join(sorted(found_emails))
    return await asyncio.to_thread(_search)


# --- Calendar implementation functions ---

async def _create_event(
    access_token: str, title: str, start: str, end: str,
    attendees: list[str] | None = None, description: str = "", location: str = "",
) -> str:
    def _create():
        service = _build_calendar_service(access_token)
        event = {
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
        params = {
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
                f"Event ID: {e['id']}\n"
                f"Title: {e.get('summary', '(no title)')}\n"
                f"Start: {start}\n"
                f"End: {end}\n"
                f"Location: {e.get('location', 'N/A')}\n"
                f"Attendees: {attendee_count}"
            )
        return "\n\n---\n\n".join(lines)
    return await asyncio.to_thread(_list)


# --- Google Docs implementation functions ---

async def _create_document(access_token: str, title: str, body_text: str = "") -> dict:
    def _create():
        docs = _build_docs_service(access_token)
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if body_text:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [{
                        "insertText": {
                            "location": {"index": 1},
                            "text": body_text,
                        }
                    }]
                },
            ).execute()

        return {
            "document_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    return await asyncio.to_thread(_create)


async def _create_presentation(
    access_token: str, title: str, slides: list[dict] | None = None,
) -> dict:
    """Create a Google Slides presentation.

    slides: optional list of dicts with 'title' and 'body' keys for each slide.
    """
    def _create():
        svc = _build_slides_service(access_token)
        pres = svc.presentations().create(body={"title": title}).execute()
        pres_id = pres["presentationId"]

        if slides:
            requests = []
            for i, slide_data in enumerate(slides):
                # Create a new blank slide (the first slide already exists)
                if i > 0:
                    requests.append({"createSlide": {"insertionIndex": i}})

            if requests:
                svc.presentations().batchUpdate(
                    presentationId=pres_id, body={"requests": requests}
                ).execute()

            # Re-fetch to get slide IDs
            pres = svc.presentations().get(presentationId=pres_id).execute()
            page_ids = [s["objectId"] for s in pres.get("slides", [])]

            text_requests = []
            for i, slide_data in enumerate(slides):
                if i >= len(page_ids):
                    break
                page_id = page_ids[i]
                # Find the title and body placeholders on each slide
                slide_obj = pres["slides"][i]
                for element in slide_obj.get("pageElements", []):
                    shape = element.get("shape", {})
                    ph = shape.get("placeholder", {})
                    ph_type = ph.get("type", "")
                    obj_id = element["objectId"]
                    if ph_type in ("TITLE", "CENTERED_TITLE") and slide_data.get("title"):
                        text_requests.append({
                            "insertText": {
                                "objectId": obj_id,
                                "text": slide_data["title"],
                                "insertionIndex": 0,
                            }
                        })
                    elif ph_type in ("BODY", "SUBTITLE") and slide_data.get("body"):
                        text_requests.append({
                            "insertText": {
                                "objectId": obj_id,
                                "text": slide_data["body"],
                                "insertionIndex": 0,
                            }
                        })

            if text_requests:
                svc.presentations().batchUpdate(
                    presentationId=pres_id, body={"requests": text_requests}
                ).execute()

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
        # Get the file name for confirmation
        file_meta = drive.files().get(fileId=file_id, fields="name,webViewLink").execute()
        return f"Shared '{file_meta.get('name', file_id)}' with {email} as {role}. Link: {file_meta.get('webViewLink', '')}"
    return await asyncio.to_thread(_share)


# --- Tool server factory ---

def create_tools_server(access_token: str | None):
    """Create an MCP server with all tools, capturing access_token via closure.

    Called once per /chat request so each request gets the correct token.
    """

    def _require_token() -> str:
        if not access_token:
            raise ValueError("No Google authentication. Log in at localhost:8000/auth/login first.")
        return access_token

    # --- Email tools ---

    @tool(
        "send_email",
        "Send a new email on behalf of the user. Write the body in their voice and style. "
        "Only call this after the user has confirmed a draft, or if they explicitly said to send directly.",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text, written in the user's voice"},
            },
            "required": ["to", "subject", "body"],
        },
    )
    async def send_email_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _send_email(token, args["to"], args["subject"], args["body"])
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "draft_email",
        "Draft an email for the user to review before sending. Shows the formatted email "
        "and asks for confirmation. Use this BEFORE send_email unless the user explicitly "
        "said to send directly.",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text, written in the user's voice"},
            },
            "required": ["to", "subject", "body"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def draft_email_tool(args: dict[str, Any]) -> dict[str, Any]:
        draft = (
            f"--- DRAFT EMAIL ---\n"
            f"To: {args['to']}\n"
            f"Subject: {args['subject']}\n\n"
            f"{args['body']}\n"
            f"--- END DRAFT ---"
        )
        return {"content": [{"type": "text", "text": draft}]}

    @tool(
        "reply_to_email",
        "Reply to an existing email thread. Use read_emails first to find the message_id "
        "and thread_id. Write the reply in the user's voice.",
        {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID (from read_emails)"},
                "thread_id": {"type": "string", "description": "Gmail thread ID (from read_emails)"},
                "body": {"type": "string", "description": "Reply body text, in the user's voice"},
            },
            "required": ["message_id", "thread_id", "body"],
        },
    )
    async def reply_to_email_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _reply_to_email(token, args["message_id"], args["thread_id"], args["body"])
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "read_emails",
        "Search and read the user's emails. Returns message IDs and thread IDs for "
        "reply_to_email. Supports Gmail search syntax: 'from:john subject:meeting', "
        "'is:unread', 'newer_than:1d'.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "limit": {"type": "integer", "description": "Max emails to return (default 5)"},
            },
            "required": ["query"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def read_emails_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        limit = args.get("limit", 5)
        result = await _read_emails(token, args["query"], limit)
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "get_contact_info",
        "Look up a contact's email address by searching recent emails for their name. "
        "Use this when the user mentions someone by name without providing their email.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The person's name to search for"},
            },
            "required": ["name"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_contact_info_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _search_contacts(token, args["name"])
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "summarize_emails",
        "Read and summarize a batch of emails. Use when the user asks for an overview "
        "of their inbox, unread emails, or emails from a specific sender/topic. "
        "Example: 'catch me up on today's emails', 'what did Sarah send me this week'.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "limit": {"type": "integer", "description": "Max emails to summarize (default 10)"},
            },
            "required": ["query"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def summarize_emails_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        limit = args.get("limit", 10)
        result = await _read_emails_with_bodies(token, args["query"], limit)
        return {"content": [{"type": "text", "text": result}]}

    # --- Calendar tools ---

    @tool(
        "create_event",
        "Create a new Google Calendar event.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time in ISO 8601 (e.g. 2026-03-29T10:00:00-04:00)"},
                "end": {"type": "string", "description": "End time in ISO 8601 format"},
                "attendees": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Attendee email addresses",
                },
                "description": {"type": "string", "description": "Event description/notes"},
                "location": {"type": "string", "description": "Event location"},
            },
            "required": ["title", "start", "end"],
        },
    )
    async def create_event_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _create_event(
            token, args["title"], args["start"], args["end"],
            attendees=args.get("attendees"), description=args.get("description", ""),
            location=args.get("location", ""),
        )
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "update_event",
        "Update an existing Google Calendar event. Use list_events first to find the "
        "event_id. Only provide fields you want to change.",
        {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Calendar event ID (from list_events)"},
                "title": {"type": "string", "description": "New event title"},
                "start": {"type": "string", "description": "New start time in ISO 8601"},
                "end": {"type": "string", "description": "New end time in ISO 8601"},
                "attendees": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Updated attendee email addresses",
                },
                "description": {"type": "string", "description": "New event description"},
                "location": {"type": "string", "description": "New event location"},
            },
            "required": ["event_id"],
        },
    )
    async def update_event_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _update_event(
            token, args["event_id"], title=args.get("title"),
            start=args.get("start"), end=args.get("end"),
            attendees=args.get("attendees"), description=args.get("description"),
            location=args.get("location"),
        )
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "delete_event",
        "Delete/cancel a Google Calendar event. Use list_events first to find the event_id.",
        {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to delete (from list_events)"},
            },
            "required": ["event_id"],
        },
    )
    async def delete_event_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _delete_event(token, args["event_id"])
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "list_events",
        "List upcoming Google Calendar events. Use to check schedule, find availability, "
        "or look up event IDs for updating/deleting.",
        {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Days to look ahead (default 7)"},
                "query": {"type": "string", "description": "Text search to filter events"},
            },
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_events_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _list_events(
            token, days_ahead=args.get("days_ahead", 7), query=args.get("query", ""),
        )
        return {"content": [{"type": "text", "text": result}]}

    # --- Google Docs / Slides / Drive tools ---

    @tool(
        "create_document",
        "Create a new Google Doc. Optionally include initial body text. "
        "Returns the document URL for sharing.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "body_text": {
                    "type": "string",
                    "description": "Initial document body content (plain text). Leave empty to create a blank doc.",
                },
            },
            "required": ["title"],
        },
    )
    async def create_document_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _create_document(token, args["title"], body_text=args.get("body_text", ""))
        text = (
            f"Created Google Doc: '{result['title']}'\n"
            f"Document ID: {result['document_id']}\n"
            f"URL: {result['url']}"
        )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "create_presentation",
        "Create a new Google Slides presentation. Optionally provide slide content as a list "
        "of objects with 'title' and 'body' fields. Returns the presentation URL.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Presentation title"},
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Slide title"},
                            "body": {"type": "string", "description": "Slide body/content text"},
                        },
                    },
                    "description": "List of slides with title and body content",
                },
            },
            "required": ["title"],
        },
    )
    async def create_presentation_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _create_presentation(token, args["title"], slides=args.get("slides"))
        text = (
            f"Created Google Slides: '{result['title']}'\n"
            f"Presentation ID: {result['presentation_id']}\n"
            f"Slides: {result['slide_count']}\n"
            f"URL: {result['url']}"
        )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "share_document",
        "Share a Google Doc, Slides, or any Drive file with someone by email. "
        "Use create_document or create_presentation first to get the file ID, "
        "or use get_contact_info to look up the recipient's email.",
        {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "Google Drive file ID (document_id or presentation_id from create tools)",
                },
                "email": {"type": "string", "description": "Recipient's email address"},
                "role": {
                    "type": "string",
                    "enum": ["reader", "commenter", "writer"],
                    "description": "Permission level (default: writer)",
                },
                "notify": {
                    "type": "boolean",
                    "description": "Send email notification to the recipient (default: true)",
                },
            },
            "required": ["file_id", "email"],
        },
    )
    async def share_document_tool(args: dict[str, Any]) -> dict[str, Any]:
        token = _require_token()
        result = await _share_document(
            token, args["file_id"], args["email"],
            role=args.get("role", "writer"), notify=args.get("notify", True),
        )
        return {"content": [{"type": "text", "text": result}]}

    # --- Web search ---

    @tool(
        "search_web",
        "Search the web for information. Use to find someone's email, check facts, "
        "get current info, or look up context needed for a task.",
        {"query": str},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def search_web_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await search_user(args["query"])
        return {"content": [{"type": "text", "text": result}]}

    # --- Bundle all tools into an MCP server ---

    return create_sdk_mcp_server(
        name="second_self",
        version="1.0.0",
        tools=[
            send_email_tool,
            draft_email_tool,
            reply_to_email_tool,
            read_emails_tool,
            get_contact_info_tool,
            summarize_emails_tool,
            create_event_tool,
            update_event_tool,
            delete_event_tool,
            list_events_tool,
            create_document_tool,
            create_presentation_tool,
            share_document_tool,
            search_web_tool,
        ],
    )
