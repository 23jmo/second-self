"""Import cookies into Chrome via CDP (Chrome DevTools Protocol)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

CDP_URL = "http://localhost:9222"
DEFAULT_STATE_PATH = Path.home() / ".secondself" / "storage_state.json"


async def get_ws_url(cdp_http_url: str = CDP_URL) -> str:
    """Fetch the browser's WebSocket debugger URL from the CDP /json/version endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{cdp_http_url}/json/version", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()

    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ConnectionError(
            f"No webSocketDebuggerUrl in CDP response from {cdp_http_url}. "
            "Is Chrome running with --remote-debugging-port?"
        )
    return ws_url


def _to_cdp_cookie_params(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Playwright storage_state cookies to CDP CookieParam format.

    Sanitizes values (strips newlines), deduplicates by name+domain+path,
    and skips cookies with empty names or domains.
    """
    seen: set[tuple[str, str, str]] = set()
    cdp_cookies = []
    skipped = 0

    for c in cookies:
        name = c.get("name", "")
        domain = c.get("domain", "")
        path = c.get("path", "/")

        # Skip invalid cookies
        if not name or not domain:
            skipped += 1
            continue

        # Deduplicate (keep first occurrence)
        dedup_key = (name, domain, path)
        if dedup_key in seen:
            skipped += 1
            continue
        seen.add(dedup_key)

        # Sanitize value: CDP rejects newlines and control characters
        value = c.get("value", "")
        value = value.replace("\n", "").replace("\r", "").replace("\x00", "")

        param: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
        }

        # Expires: CDP uses seconds since epoch. -1 or missing = session cookie.
        expires = c.get("expires")
        if expires is not None and expires > 0:
            param["expires"] = expires

        if c.get("httpOnly"):
            param["httpOnly"] = True
        if c.get("secure"):
            param["secure"] = True

        same_site = c.get("sameSite")
        if same_site and same_site in ("Strict", "Lax", "None"):
            param["sameSite"] = same_site

        cdp_cookies.append(param)

    if skipped:
        logger.info(f"Skipped {skipped} cookies (invalid/duplicate)")

    return cdp_cookies


def _filter_by_domains(cookies: list[dict[str, Any]], domains: list[str]) -> list[dict[str, Any]]:
    """Filter cookies by domain suffix."""
    filtered = []
    for c in cookies:
        cookie_domain = c.get("domain", "").lstrip(".")
        for domain in domains:
            domain = domain.lstrip(".")
            if cookie_domain == domain or cookie_domain.endswith(f".{domain}"):
                filtered.append(c)
                break
    return filtered


async def import_cookies_via_cdp(
    cookies: list[dict[str, Any]],
    cdp_url: str = CDP_URL,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """Import cookies into Chrome via CDP Storage.setCookies.

    Args:
        cookies: Cookie dicts in Playwright/CookieParam format.
        cdp_url: CDP HTTP endpoint URL.
        clear_existing: Clear all existing cookies before import.

    Returns:
        {"status": "ok", "imported": count, "cleared": bool}
    """
    from cdp_use import CDPClient

    ws_url = await get_ws_url(cdp_url)
    logger.info(f"Connecting to Chrome CDP at {ws_url}")

    async with CDPClient(ws_url) as client:
        if clear_existing:
            await client.send.Storage.clearCookies()
            logger.info("Cleared existing cookies")

        cdp_cookies = _to_cdp_cookie_params(cookies)
        if cdp_cookies:
            await client.send.Storage.setCookies(params={"cookies": cdp_cookies})
            logger.info(f"Injected {len(cdp_cookies)} cookies via CDP")

    return {
        "status": "ok",
        "imported": len(cdp_cookies),
        "cleared": clear_existing,
    }


async def import_from_file(
    storage_state_path: str | Path = DEFAULT_STATE_PATH,
    cdp_url: str = CDP_URL,
    domains: list[str] | None = None,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """Load storage_state.json and import cookies via CDP.

    Args:
        storage_state_path: Path to the storage_state.json file.
        cdp_url: CDP endpoint URL.
        domains: Optional domain filter applied at import time.
        clear_existing: Clear existing cookies before import.

    Returns:
        {"status": "ok", "imported": count, "cleared": bool, "source": path}
    """
    path = Path(storage_state_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Storage state file not found at {path}. "
            "Run export first: python -m cookie_sync.sync --export-only"
        )

    state = json.loads(path.read_text(encoding="utf-8"))
    cookies = state.get("cookies", [])

    if domains:
        cookies = _filter_by_domains(cookies, domains)
        logger.info(f"Filtered to {len(cookies)} cookies for domains: {domains}")

    result = await import_cookies_via_cdp(cookies, cdp_url, clear_existing)
    result["source"] = str(path)
    return result


def import_cookies_sync(
    storage_state_path: str | Path = DEFAULT_STATE_PATH,
    cdp_url: str = CDP_URL,
    domains: list[str] | None = None,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """Synchronous wrapper for import_from_file. Used by agent-server."""
    return asyncio.run(
        import_from_file(storage_state_path, cdp_url, domains, clear_existing)
    )
