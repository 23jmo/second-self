"""Productivity tools for the unified orchestrator.

Provides Anthropic-format tool definitions and execution for Gmail,
Calendar, Google Docs/Slides/Drive, and web search. The actual Google
API calls are ported from src/agent/tools.py (which depends on the
uninstalled claude_agent_sdk) so the orchestrator has no SDK dependency.
"""

import asyncio
import base64
import json
import logging
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Google service builders
# ---------------------------------------------------------------------------

def _gmail(token: str):
    return build("gmail", "v1", credentials=Credentials(token=token))

def _calendar(token: str):
    return build("calendar", "v3", credentials=Credentials(token=token))

def _docs(token: str):
    return build("docs", "v1", credentials=Credentials(token=token))

def _slides(token: str):
    return build("slides", "v1", credentials=Credentials(token=token))

def _drive(token: str):
    return build("drive", "v3", credentials=Credentials(token=token))


# ---------------------------------------------------------------------------
# Anthropic-format tool definitions
# ---------------------------------------------------------------------------

PRODUCTIVITY_TOOLS = [
    {
        "name": "send_email",
        "description": (
            "Send a new email on behalf of the user. Write the body in their voice. "
            "Only call after the user confirmed a draft, or if they said to send directly."
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
            "Draft an email for the user to review before sending. Use this BEFORE "
            "send_email unless the user explicitly said to send directly."
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
            "Reply to an existing email thread. Use read_emails first to find the "
            "message_id and thread_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID (from read_emails)"},
                "thread_id": {"type": "string", "description": "Gmail thread ID (from read_emails)"},
                "body": {"type": "string", "description": "Reply body text"},
            },
            "required": ["message_id", "thread_id", "body"],
        },
    },
    {
        "name": "read_emails",
        "description": (
            "Search and read the user's emails. Supports Gmail search syntax: "
            "'from:john subject:meeting', 'is:unread', 'newer_than:1d'."
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
            "Read and summarize a batch of emails. Use when the user asks for inbox "
            "overview or email summaries."
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
                    "type": "array", "items": {"type": "string"},
                    "description": "Attendee email addresses",
                },
                "description": {"type": "string", "description": "Event description"},
                "location": {"type": "string", "description": "Event location"},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "update_event",
        "description": (
            "Update an existing Google Calendar event. Use list_events first to find the event_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Calendar event ID"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete a Google Calendar event.",
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
                "body_text": {"type": "string", "description": "Initial body content"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_presentation",
        "description": "Create a new Google Slides presentation. Returns the URL.",
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
                "email": {"type": "string", "description": "Recipient email address"},
                "role": {"type": "string", "enum": ["reader", "commenter", "writer"]},
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
]

# Names for quick lookup
PRODUCTIVITY_TOOL_NAMES = {t["name"] for t in PRODUCTIVITY_TOOLS}


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def execute_productivity_tool(
    tool_name: str, args: dict[str, Any], access_token: str | None, tavily_key: str | None,
) -> str:
    """Execute a productivity tool and return the result as a string."""
    if tool_name in (
        "send_email", "draft_email", "reply_to_email", "read_emails",
        "get_contact_info", "summarize_emails",
        "create_event", "update_event", "delete_event", "list_events",
        "create_document", "create_presentation", "share_document",
    ):
        if not access_token:
            return json.dumps({"error": "No Google authentication. Log in at localhost:8000/auth/login first."})

    try:
        if tool_name == "send_email":
            result = await _exec_send_email(access_token, args)
        elif tool_name == "draft_email":
            result = _exec_draft_email(args)
        elif tool_name == "reply_to_email":
            result = await _exec_reply_to_email(access_token, args)
        elif tool_name == "read_emails":
            result = await _exec_read_emails(access_token, args)
        elif tool_name == "get_contact_info":
            result = await _exec_get_contact_info(access_token, args)
        elif tool_name == "summarize_emails":
            result = await _exec_summarize_emails(access_token, args)
        elif tool_name == "create_event":
            result = await _exec_create_event(access_token, args)
        elif tool_name == "update_event":
            result = await _exec_update_event(access_token, args)
        elif tool_name == "delete_event":
            result = await _exec_delete_event(access_token, args)
        elif tool_name == "list_events":
            result = await _exec_list_events(access_token, args)
        elif tool_name == "create_document":
            result = await _exec_create_document(access_token, args)
        elif tool_name == "create_presentation":
            result = await _exec_create_presentation(access_token, args)
        elif tool_name == "share_document":
            result = await _exec_share_document(access_token, args)
        elif tool_name == "search_web":
            result = await _exec_search_web(args, tavily_key)
        else:
            return json.dumps({"error": f"Unknown productivity tool: {tool_name}"})

        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        log.error(f"Productivity tool {tool_name} failed: {e}")
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------

async def _exec_send_email(token: str, args: dict) -> str:
    def _send():
        service = _gmail(token)
        msg = MIMEText(args["body"])
        msg["to"] = args["to"]
        msg["subject"] = args["subject"]
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email sent to {args['to']} with subject '{args['subject']}'"
    return await asyncio.to_thread(_send)


def _exec_draft_email(args: dict) -> str:
    return (
        f"--- DRAFT EMAIL ---\n"
        f"To: {args['to']}\n"
        f"Subject: {args['subject']}\n\n"
        f"{args['body']}\n"
        f"--- END DRAFT ---"
    )


async def _exec_reply_to_email(token: str, args: dict) -> str:
    def _reply():
        service = _gmail(token)
        original = service.users().messages().get(
            userId="me", id=args["message_id"], format="metadata",
            metadataHeaders=["Subject", "From", "To", "Message-ID"],
        ).execute()
        headers = {h["name"]: h["value"] for h in original["payload"].get("headers", [])}
        reply_to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        msg = MIMEText(args["body"])
        msg["to"] = reply_to
        msg["subject"] = subject
        msg["In-Reply-To"] = headers.get("Message-ID", "")
        msg["References"] = headers.get("Message-ID", "")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": args["thread_id"]}
        ).execute()
        return f"Reply sent to {reply_to} in thread '{subject}'"
    return await asyncio.to_thread(_reply)


async def _exec_read_emails(token: str, args: dict) -> str:
    def _read():
        service = _gmail(token)
        limit = args.get("limit", 5)
        results = service.users().messages().list(userId="me", q=args["query"], maxResults=limit).execute()
        emails = []
        for m in results.get("messages", []):
            full = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
            h = {hd["name"]: hd["value"] for hd in full["payload"].get("headers", [])}
            emails.append(
                f"Message ID: {m['id']}\nThread ID: {full.get('threadId', '')}\n"
                f"From: {h.get('From', '?')}\nTo: {h.get('To', '?')}\n"
                f"Subject: {h.get('Subject', '?')}\nDate: {h.get('Date', '?')}\n"
                f"Preview: {full.get('snippet', '')}"
            )
        return "\n\n---\n\n".join(emails) if emails else "No emails found matching that query."
    return await asyncio.to_thread(_read)


async def _exec_get_contact_info(token: str, args: dict) -> str:
    def _search():
        service = _gmail(token)
        name = args["name"]
        found = set()
        for q in [f"from:{name}", f"to:{name}"]:
            results = service.users().messages().list(userId="me", q=q, maxResults=10).execute()
            for m in results.get("messages", []):
                full = service.users().messages().get(
                    userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "To"],
                ).execute()
                h = {hd["name"]: hd["value"] for hd in full["payload"].get("headers", [])}
                for field in ["From", "To"]:
                    val = h.get(field, "")
                    if name.lower() in val.lower():
                        found.add(val)
        if not found:
            return f"No email addresses found for '{name}'."
        return f"Found contacts matching '{name}':\n" + "\n".join(sorted(found))
    return await asyncio.to_thread(_search)


async def _exec_summarize_emails(token: str, args: dict) -> str:
    def _read():
        service = _gmail(token)
        limit = args.get("limit", 10)
        results = service.users().messages().list(userId="me", q=args["query"], maxResults=limit).execute()
        emails = []
        for m in results.get("messages", []):
            full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            h = {hd["name"]: hd["value"] for hd in full["payload"].get("headers", [])}
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
                f"From: {h.get('From', '?')}\nSubject: {h.get('Subject', '?')}\n"
                f"Date: {h.get('Date', '?')}\nBody:\n{body_text}"
            )
        return "\n\n===\n\n".join(emails) if emails else "No emails found matching that query."
    return await asyncio.to_thread(_read)


async def _exec_create_event(token: str, args: dict) -> str:
    def _create():
        service = _calendar(token)
        event = {"summary": args["title"], "start": {"dateTime": args["start"]}, "end": {"dateTime": args["end"]}}
        if args.get("attendees"):
            event["attendees"] = [{"email": e} for e in args["attendees"]]
        if args.get("description"):
            event["description"] = args["description"]
        if args.get("location"):
            event["location"] = args["location"]
        created = service.events().insert(calendarId="primary", body=event).execute()
        return f"Event '{args['title']}' created: {created.get('htmlLink', '')}"
    return await asyncio.to_thread(_create)


async def _exec_update_event(token: str, args: dict) -> str:
    def _update():
        service = _calendar(token)
        existing = service.events().get(calendarId="primary", eventId=args["event_id"]).execute()
        for field, key in [("title", "summary"), ("description", "description"), ("location", "location")]:
            if args.get(field) is not None:
                existing[key] = args[field]
        if args.get("start"):
            existing["start"] = {"dateTime": args["start"]}
        if args.get("end"):
            existing["end"] = {"dateTime": args["end"]}
        updated = service.events().update(calendarId="primary", eventId=args["event_id"], body=existing).execute()
        return f"Event '{updated.get('summary', '')}' updated: {updated.get('htmlLink', '')}"
    return await asyncio.to_thread(_update)


async def _exec_delete_event(token: str, args: dict) -> str:
    def _delete():
        service = _calendar(token)
        service.events().delete(calendarId="primary", eventId=args["event_id"]).execute()
        return f"Event {args['event_id']} deleted."
    return await asyncio.to_thread(_delete)


async def _exec_list_events(token: str, args: dict) -> str:
    def _list():
        from datetime import datetime, timedelta, timezone
        service = _calendar(token)
        now = datetime.now(timezone.utc)
        days = args.get("days_ahead", 7)
        params = {
            "calendarId": "primary",
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=days)).isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 20,
        }
        if args.get("query"):
            params["q"] = args["query"]
        events = service.events().list(**params).execute().get("items", [])
        if not events:
            return f"No events found in the next {days} days."
        lines = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", "?"))
            lines.append(f"Event ID: {e['id']}\nTitle: {e.get('summary', '(no title)')}\nStart: {start}")
        return "\n\n---\n\n".join(lines)
    return await asyncio.to_thread(_list)


async def _exec_create_document(token: str, args: dict) -> str:
    def _create():
        docs = _docs(token)
        doc = docs.documents().create(body={"title": args["title"]}).execute()
        doc_id = doc["documentId"]
        if args.get("body_text"):
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": args["body_text"]}}]},
            ).execute()
        return f"Created Google Doc: '{args['title']}'\nID: {doc_id}\nURL: https://docs.google.com/document/d/{doc_id}/edit"
    return await asyncio.to_thread(_create)


async def _exec_create_presentation(token: str, args: dict) -> str:
    def _create():
        svc = _slides(token)
        pres = svc.presentations().create(body={"title": args["title"]}).execute()
        pres_id = pres["presentationId"]
        slide_count = 1
        if args.get("slides"):
            slide_count = len(args["slides"])
            if slide_count > 1:
                requests = [{"createSlide": {"insertionIndex": i}} for i in range(1, slide_count)]
                svc.presentations().batchUpdate(presentationId=pres_id, body={"requests": requests}).execute()
        return (
            f"Created Google Slides: '{args['title']}'\n"
            f"ID: {pres_id}\nSlides: {slide_count}\n"
            f"URL: https://docs.google.com/presentation/d/{pres_id}/edit"
        )
    return await asyncio.to_thread(_create)


async def _exec_share_document(token: str, args: dict) -> str:
    def _share():
        drive = _drive(token)
        role = args.get("role", "writer")
        drive.permissions().create(
            fileId=args["file_id"],
            body={"type": "user", "role": role, "emailAddress": args["email"]},
            sendNotificationEmail=True,
        ).execute()
        meta = drive.files().get(fileId=args["file_id"], fields="name,webViewLink").execute()
        return f"Shared '{meta.get('name', args['file_id'])}' with {args['email']} as {role}."
    return await asyncio.to_thread(_share)


async def _exec_search_web(args: dict, tavily_key: str | None) -> str:
    if not tavily_key:
        return json.dumps({"error": "TAVILY_API_KEY not set"})

    def _search():
        import urllib.request
        payload = {
            "api_key": tavily_key,
            "query": args["query"],
            "search_depth": "advanced",
            "max_results": 5,
            "include_answer": True,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        answer = result.get("answer", "")
        snippets = [r.get("content", "")[:200] for r in result.get("results", [])[:3]]
        return answer + "\n\nSources:\n" + "\n".join(snippets) if answer else "\n".join(snippets)

    return await asyncio.to_thread(_search)
