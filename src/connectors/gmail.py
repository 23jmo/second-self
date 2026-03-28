"""Gmail connector — fetches sent mail.

Sent mail is the user's voice. Inbox is other people's voices.
"""

import asyncio
import base64

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.models.schemas import EmailMessage


def _fetch_sent_emails(access_token: str, limit: int = 100) -> list[EmailMessage]:
    """Synchronous Gmail API calls (run in thread pool)."""
    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["SENT"], maxResults=limit)
        .execute()
    )

    messages = []
    for msg in results.get("messages", []):
        full = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="full")
            .execute()
        )

        payload = full["payload"]
        headers = payload.get("headers", [])

        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"), ""
        )
        to = next((h["value"] for h in headers if h["name"].lower() == "to"), "")

        body = _decode_body(payload)

        messages.append(
            EmailMessage(
                subject=subject,
                to=to,
                body=body[:400],  # truncate to avoid context limits
                date=full.get("internalDate", ""),
            )
        )

    return messages


def _decode_body(payload: dict) -> str:
    """Extract and decode the email body from a Gmail payload."""
    body = ""

    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                break
    elif "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    # Strip HTML if needed
    if "<" in body and ">" in body:
        body = BeautifulSoup(body, "html.parser").get_text()

    return body.strip()


async def get_sent_emails(access_token: str, limit: int = 100) -> list[EmailMessage]:
    """Async wrapper — runs Gmail API calls in a thread pool."""
    return await asyncio.to_thread(_fetch_sent_emails, access_token, limit)
