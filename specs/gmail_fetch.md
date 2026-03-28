# Spec: fetch/gmail_fetch.py

**Purpose:** Fetch up to 2000 emails from Gmail (INBOX + SENT), extract structured
fields, deduplicate across labels, cache to disk, and return a list of email dicts
for the downstream cleaner and analyzers.

---

## Dependencies

- `auth.gmail_auth.get_gmail_credentials()` for a `google.oauth2.credentials.Credentials` object
- `googleapiclient.discovery.build` to construct the Gmail service
- `python-dotenv` to load `.env`

---

## Email cap and label split

- **Total cap:** 2000 emails
- **Fixed split:** up to 1000 INBOX + up to 1000 SENT
- Fetch most recent first (Gmail default ordering)
- Fetch each label independently, then merge

---

## API call strategy

### Step 1: List message IDs

For each label (`INBOX`, `SENT`):
- Call `service.users().messages().list(userId='me', labelIds=[label], maxResults=500)`
- Paginate with `nextPageToken` until 1000 IDs collected or no more pages
- This returns only message IDs (minimal quota cost)

### Step 2: Batch get full messages

- Use `service.new_batch_http_request()` to fetch full message content
- Gmail batch API limit: **100 requests per batch call**
- For 2000 emails: up to 20 batch rounds
- **No delay between batches** — fire immediately. Gmail's personal quota (250 units/sec) is sufficient
- Each message requested with `format='full'` (returns headers + MIME parts)

### Step 3: Parse each message

Extract from the API response:

| Field | Source |
|-------|--------|
| `id` | `message["id"]` |
| `threadId` | `message["threadId"]` |
| `labelIds` | `message["labelIds"]` |
| `subject` | Header: `Subject` |
| `from_address` | Header: `From` |
| `to_addresses` | Header: `To`, split on `,`, strip whitespace → list |
| `cc_addresses` | Header: `Cc`, split on `,`, strip whitespace → list (empty list if absent) |
| `date_unix` | `int(message["internalDate"]) // 1000` (API returns milliseconds) |
| `body_raw` | MIME part extraction (see below) |

---

## MIME body extraction

Walk the full MIME tree recursively:

1. If `payload.mimeType` is `text/plain` → decode and return (base64url decode `body.data`)
2. If `payload.mimeType` is `text/html` → store as fallback
3. If `payload.mimeType` starts with `multipart/` → recurse into `payload.parts`
4. Return the first `text/plain` found. If none, return `text/html` fallback
5. If neither found → set `body_raw` to empty string

Base64url decoding: use `base64.urlsafe_b64decode(data + '==')` (Gmail pads inconsistently).

---

## Deduplication

After merging INBOX and SENT results:
- Deduplicate by `id` (message ID)
- When the same ID appears in both label sets: **keep the SENT version** (it has the user's authored content, which is more valuable for voice analysis). Drop the INBOX copy entirely.

---

## Parse error handling

If any individual message fails to parse (missing headers, corrupted MIME, missing body data):
- **Log a warning** with the message ID and error
- **Skip the message** — do not include it in results
- Never crash the batch over a single bad email

---

## Caching

- Cache file: `output/raw_emails.json`
- TTL: **24 hours**
- Check: `time.time() - fetched_at < 86400`
- If cache is fresh → load from disk, log `"Using cached emails"`, return immediately
- `force_refresh=False` parameter on `fetch_emails()` — pass `True` to bypass cache (main.py passes `--no-cache`)
- Write atomically: tmp file + rename

### Cache file structure

```json
{
  "fetched_at": 1743000000,
  "label_counts": {
    "INBOX": 987,
    "SENT": 543
  },
  "total": 1530,
  "emails": [ ... ]
}
```

- `label_counts` reflects per-label counts **before** deduplication
- `total` is the final count after dedup
- No compression — plain JSON

---

## Auth failure handling

If Gmail API returns a 401/403 (expired or revoked credentials) at any point:
- **Let it crash** with a clear error message
- Log: `"Gmail credentials expired or revoked. Re-run auth: python -m auth.firebase_auth"`
- Re-raise the `HttpError` — do not retry auth automatically from inside the fetch module
- Do not save partial results to cache

---

## Public API

```python
def fetch_emails(force_refresh: bool = False) -> list[dict]:
    """Fetch emails from Gmail (INBOX + SENT). Returns list of email dicts.

    Uses a 24h on-disk cache. Pass force_refresh=True to bypass.
    Raises on auth failure. Skips unparseable emails with a warning.
    """
```

---

## CLI entrypoint

```python
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, ...)
    emails = fetch_emails()
    inbox_count = sum(1 for e in emails if "INBOX" in e.get("labelIds", []))
    sent_count = sum(1 for e in emails if "SENT" in e.get("labelIds", []))
    print(f"Fetched {len(emails)} emails (INBOX: {inbox_count}, SENT: {sent_count})")
```

---

## Module conventions

- `logging` only — no `print()` except in `__main__` block
- Type hints on all functions
- `output/` directory created with `Path.mkdir(parents=True, exist_ok=True)` before writing
- Constants: `CACHE_PATH = Path("output/raw_emails.json")`, `CACHE_MAX_AGE_HOURS = 24`, `EMAIL_CAP = 2000`, `PER_LABEL_CAP = 1000`, `BATCH_SIZE = 100`
- Independently runnable: `python -m fetch.gmail_fetch`

---

## Error cases summary

| Condition | Behavior |
|-----------|----------|
| Auth expired (401/403) | Log clear message, re-raise HttpError |
| Single email parse failure | Log warning with message ID, skip email |
| 0 emails returned | Log warning, return `[]`, write empty cache |
| Cache file corrupt | Log warning, re-fetch fresh |
| `output/` directory missing | Create it before writing |
| Rate limit (429) | Let `googleapiclient` handle default retry (it has built-in exponential backoff) |
