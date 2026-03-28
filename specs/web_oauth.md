# Spec: Firebase JS SDK Web Auth

## Summary

Replace the CLI-based server-side OAuth flow (`auth/firebase_auth.py`) with a Firebase JS SDK browser-based auth flow. A lightweight FastAPI server serves a login page, the user authenticates via Firebase popup in the browser, the browser POSTs the Google access token back to the server, the server persists it to disk and shuts down, and the pipeline continues.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Firebase SDK style | Copy friend's modular ESM (v11) | Proven to work, modern, minimal |
| Token expiry handling | Auto re-open browser | `run_auth_server()` checks cache first; if expired, runs the flow again seamlessly |
| Token file path | Same path (`~/.secondself/firebase_token.json`), new format | No refresh_token field; adds email, display_name. Old tokens are simply overwritten |
| ID token verification | Skip | Local-only pipeline over localhost. No security benefit to verifying. |
| Server lifecycle | Shut down after auth | Start server -> capture token -> kill server -> run pipeline. Port 8080 freed. |
| Login UI | Copy friend's dark theme design | Clean, proven, briefly visible |
| `--tavily-only` behavior | Skip auth entirely | No browser, no server. Fastest path. |

## Env vars required

All three must be in `.env` (user confirmed they exist):

```
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
```

Existing vars still needed: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (for backward compat, not used in new flow).

## Files to create

### 1. `static/login.html`

Firebase JS SDK popup auth page. Copied from `origin/mcp:src/static/login.html` with these adjustments:

- Uses Firebase JS SDK v11 modular ESM imports (same as friend's)
- Fetches Firebase config from `GET /auth/firebase-config`
- Creates `GoogleAuthProvider` with `addScope('https://www.googleapis.com/auth/gmail.readonly')`
- On button click: `signInWithPopup(auth, provider)`
- Extracts `GoogleAuthProvider.credentialFromResult(result).accessToken` (the Google OAuth access token)
- Extracts `result.user.getIdToken()` (Firebase ID token — stored but not verified)
- Extracts `result.user.email` and `result.user.displayName`
- POSTs `{ google_access_token, id_token, email, display_name }` to `POST /auth/callback`
- Shows success message: "Authenticated as {name}. You can close this window."
- Dark theme (#0a0a0a background), same styling as friend's version

### 2. `auth/web_oauth.py`

FastAPI app + server lifecycle manager.

**FastAPI routes:**

- `GET /auth/firebase-config` — Returns `{ apiKey, authDomain, projectId }` from env vars
- `GET /auth/login` — Serves `static/login.html` via `FileResponse`
- `POST /auth/callback` — Receives `{ google_access_token, id_token, email, display_name }`:
  - Saves to `~/.secondself/firebase_token.json` with `saved_at` and `expires_in: 3600`
  - Sets a `threading.Event` to signal auth completion
  - Returns `{ status: "ok" }`

**Token cache format** (`~/.secondself/firebase_token.json`):

```json
{
  "access_token": "ya29...",
  "id_token": "eyJ...",
  "email": "user@example.com",
  "display_name": "User Name",
  "expires_in": 3600,
  "saved_at": 1711300000
}
```

**Token cache functions:**

- `_load_token() -> dict | None` — Load from disk. Return None if missing or corrupt.
- `_is_token_valid(token: dict) -> bool` — Check `saved_at + expires_in - 60 > now`.
- `_save_token(data: dict) -> dict` — Write to disk with `saved_at` timestamp. Return new dict (no mutation).

**Public function — `run_auth_server() -> dict`:**

```
1. Load .env
2. Call _load_token()
3. If valid → log "Using cached token", return token dict
4. Create threading.Event (auth_complete)
5. Configure uvicorn.Server on port 8080, background thread
6. Start server thread
7. Open browser to http://localhost:8080/auth/login
8. auth_complete.wait(timeout=120)
9. If timeout → raise TimeoutError with clear message
10. Signal uvicorn shutdown (server.should_exit = True)
11. Join server thread
12. Return captured token dict
```

Port: 8080 (same as before). If port is in use, raise `OSError` with clear message.

Use `threading.Thread(daemon=True)` for the server so it doesn't block process exit.

**Module-level state for callback signaling:**

```python
_captured_token: dict | None = None
_auth_event: threading.Event | None = None
```

The `/auth/callback` route sets `_captured_token` and calls `_auth_event.set()`.

### 3. `tests/test_web_oauth.py`

Using `fastapi.testclient.TestClient`:

- `test_firebase_config_returns_env_vars` — Patch env, verify response JSON
- `test_callback_saves_token` — POST valid payload, verify file written to disk (use tmp_path)
- `test_callback_missing_fields` — POST incomplete payload, verify 422
- `test_load_token_missing_file` — Returns None
- `test_load_token_valid` — Returns dict
- `test_load_token_corrupt` — Returns None
- `test_is_token_valid_fresh` — Returns True
- `test_is_token_valid_expired` — Returns False
- `test_run_auth_server_uses_cache` — Mock _load_token to return valid token, verify no server started
- `test_run_auth_server_timeout` — Mock _load_token to return None, mock server to never complete, verify TimeoutError

## Files to modify

### 4. `auth/gmail_auth.py`

Add one new function:

```python
def get_gmail_credentials_from_token(access_token: str) -> Credentials:
    """Build Gmail API Credentials from a raw Google access token."""
    return Credentials(token=access_token)
```

No client_id/client_secret/refresh_token needed — Firebase JS SDK tokens are standalone.

Keep `get_gmail_credentials()` unchanged for backward compatibility.

### 5. `fetch/gmail_fetch.py`

Modify `_build_service()`:

```python
def _build_service(access_token: str | None = None) -> Any:
    if access_token:
        from auth.gmail_auth import get_gmail_credentials_from_token
        creds = get_gmail_credentials_from_token(access_token)
    else:
        creds = get_gmail_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
```

Modify `fetch_emails()` signature:

```python
def fetch_emails(force_refresh: bool = False, access_token: str | None = None) -> list[dict[str, Any]]:
```

Pass `access_token` through to `_build_service(access_token)`.

### 6. `main.py`

**`_run_full_pipeline(no_cache, dry_run)`:**

Replace Steps 1-2 (firebase auth + gmail credentials) with:

```python
from auth.web_oauth import run_auth_server

logger.info("Step 1: Authenticating via Firebase...")
token = run_auth_server()
access_token = token["access_token"]
```

Step 4 (Gmail fetch) becomes:

```python
raw_emails = fetch_emails(force_refresh=no_cache, access_token=access_token)
```

Remove imports of `get_firebase_token` and `get_gmail_credentials`.

**`_run_tavily_only(no_cache, dry_run)`:**

No auth at all. No changes needed (it already doesn't call auth).

### 7. `requirements.txt`

Add:

```
fastapi
uvicorn[standard]
```

### 8. `tests/test_main.py`

Update patches:
- Replace `auth.firebase_auth.get_firebase_token` and `auth.gmail_auth.get_gmail_credentials` patches with `auth.web_oauth.run_auth_server` returning `{"access_token": "fake"}`.
- Update `fetch.gmail_fetch.fetch_emails` mock to accept `access_token` kwarg.

### 9. `tests/test_gmail_auth.py`

Add:
- `test_get_gmail_credentials_from_token` — verify it returns a Credentials with the correct token value.

### 10. `tests/test_gmail_fetch.py`

Add:
- `test_build_service_with_access_token` — verify it calls `get_gmail_credentials_from_token` when token provided.
- `test_fetch_emails_passes_access_token` — verify access_token flows through to `_build_service`.

## Files NOT changed

- `auth/firebase_auth.py` — Deprecated, not deleted. Tests remain.
- `clean/email_cleaner.py` — Untouched
- `analyze/*.py` — All untouched
- `build/identity_builder.py` — Untouched
- All existing analyzer tests — Untouched

## Error handling

- Port 8080 in use → `OSError` with message: "Port 8080 is already in use. Stop the process using it and retry."
- Auth timeout (120s) → `TimeoutError` with message: "No authentication received within 120s. Complete the browser sign-in and try again."
- Missing Firebase env vars → `EnvironmentError` listing which vars are missing.
- Expired token mid-pipeline (Gmail fetch fails with 401/403) → existing error message in `gmail_fetch.py` already covers this.

## Build order

1. `requirements.txt` — add fastapi, uvicorn
2. `static/login.html` — Firebase popup auth page
3. `auth/web_oauth.py` — FastAPI server + token caching + `run_auth_server()`
4. `auth/gmail_auth.py` — add `get_gmail_credentials_from_token()`
5. `fetch/gmail_fetch.py` — add optional `access_token` param
6. `main.py` — wire `run_auth_server()` into pipeline
7. `tests/test_web_oauth.py` — new tests
8. `tests/test_main.py` — update patches
9. `tests/test_gmail_auth.py` — add token test
10. `tests/test_gmail_fetch.py` — add token passthrough test
