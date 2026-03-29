"""Export cookies from Chrome via CDP (Chrome DevTools Protocol).

Launches a temporary headless Chrome with a copy of the user's profile,
extracts cookies via CDP Storage.getCookies(), then cleans up. This approach
works with Chrome 130+ App-Bound Encryption where direct SQLite reading fails.
"""

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CHROME_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
ARC_DIR = Path.home() / "Library" / "Application Support" / "Arc" / "User Data"
DEFAULT_OUTPUT = Path.home() / ".secondself" / "storage_state.json"

# Known Chromium-based browsers on macOS and their data directories
BROWSER_DATA_DIRS: dict[str, Path] = {
    "Google Chrome": CHROME_DIR,
    "Arc": ARC_DIR,
}


@dataclass
class ProfileInfo:
    """A browser profile with enough info to launch and identify it."""
    browser: str        # "Google Chrome", "Arc"
    directory: str      # "Profile 5", "Default"
    display_name: str   # "Johnathan", "Work"
    user_data_dir: Path # /Users/.../Google/Chrome


def get_chrome_profiles() -> dict[str, str]:
    """Return {directory_name: display_name} for all Chrome profiles.

    Kept for backward compatibility with orchestrator and CLI code.
    """
    local_state_path = CHROME_DIR / "Local State"
    if not local_state_path.exists():
        raise FileNotFoundError(f"Chrome Local State not found at {local_state_path}")

    local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
    info_cache = local_state.get("profile", {}).get("info_cache", {})
    return {
        dir_name: info.get("name", dir_name)
        for dir_name, info in info_cache.items()
    }


def get_default_profile() -> str:
    """Return the last-used Chrome profile directory name."""
    local_state_path = CHROME_DIR / "Local State"
    if not local_state_path.exists():
        raise FileNotFoundError(f"Chrome Local State not found at {local_state_path}")

    local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
    last_used = local_state.get("profile", {}).get("last_used")
    if not last_used:
        raise RuntimeError("Could not determine last-used Chrome profile from Local State")
    return last_used


def _read_profiles_from_local_state(browser: str, data_dir: Path) -> list[ProfileInfo]:
    """Read profiles from a Chromium browser's Local State file."""
    local_state_path = data_dir / "Local State"
    if not local_state_path.exists():
        return []

    try:
        local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
        info_cache = local_state.get("profile", {}).get("info_cache", {})
        return [
            ProfileInfo(
                browser=browser,
                directory=dir_name,
                display_name=info.get("name", dir_name),
                user_data_dir=data_dir,
            )
            for dir_name, info in info_cache.items()
        ]
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read profiles from {local_state_path}: {e}")
        return []


def get_all_profiles() -> list[ProfileInfo]:
    """Return all profiles across all detected Chromium-based browsers."""
    profiles: list[ProfileInfo] = []
    for browser, data_dir in BROWSER_DATA_DIRS.items():
        if data_dir.exists():
            profiles.extend(_read_profiles_from_local_state(browser, data_dir))
    return profiles


def resolve_profile(
    profile_name: str | None,
    browser: str | None = None,
) -> ProfileInfo:
    """Resolve a profile name/directory to a ProfileInfo.

    Accepts directory names ("Profile 5") or display names ("Work").
    If browser is specified, only searches that browser's profiles.
    If profile_name is None, returns Chrome's last-used profile.
    """
    all_profiles = get_all_profiles()

    if profile_name is None:
        default_dir = get_default_profile()
        for p in all_profiles:
            if p.browser == "Google Chrome" and p.directory == default_dir:
                return p
        # Fallback if not in all_profiles
        return ProfileInfo(
            browser="Google Chrome",
            directory=default_dir,
            display_name=default_dir,
            user_data_dir=CHROME_DIR,
        )

    candidates = all_profiles
    if browser:
        candidates = [p for p in candidates if p.browser.lower() == browser.lower()]

    # Try exact directory name match first
    for p in candidates:
        if p.directory == profile_name:
            return p

    # Try case-insensitive display name match
    name_lower = profile_name.lower()
    matches = [p for p in candidates if p.display_name.lower() == name_lower]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        lines = [f"Multiple profiles match '{profile_name}'. Specify --browser or use the directory name:"]
        for p in matches:
            lines.append(f"  {p.browser} / {p.directory}: {p.display_name}")
        raise ValueError("\n".join(lines))

    # Try case-insensitive directory name match
    for p in candidates:
        if p.directory.lower() == name_lower:
            return p

    lines = [f"Unknown profile '{profile_name}'. Available profiles:"]
    for p in all_profiles:
        lines.append(f"  {p.browser} / {p.directory}: {p.display_name}")
    raise ValueError("\n".join(lines))


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


async def _export_cookies_cdp(
    profile_info: ProfileInfo,
    domains: list[str] | None = None,
    include_session_cookies: bool = True,
) -> dict[str, Any]:
    """Extract cookies via CDP by launching a temp Chrome with the user's profile.

    BrowserSession automatically copies the profile to a temp directory,
    so this works even when the user's Chrome is running.
    """
    from browser_use import BrowserSession
    from browser_use.skill_cli.utils import find_chrome_executable

    chrome_path = find_chrome_executable()
    if not chrome_path:
        raise RuntimeError(
            "Chrome not found. Install Google Chrome or set executable_path manually."
        )

    session = BrowserSession(
        executable_path=chrome_path,
        user_data_dir=str(profile_info.user_data_dir),
        profile_directory=profile_info.directory,
        headless=True,
        # Minimal setup — we only need CDP cookie access, not browsing
        enable_default_extensions=False,
        captcha_solver=False,
        highlight_elements=False,
        dom_highlight_elements=False,
    )

    temp_dir: Optional[str] = None
    try:
        await session.start()
        # After start(), _copy_profile() has set user_data_dir to the temp copy
        temp_dir = str(session.browser_profile.user_data_dir)

        storage_state = await session.export_storage_state()
        logger.info(
            f"Extracted {len(storage_state.get('cookies', []))} cookies "
            f"from {profile_info.browser} / {profile_info.display_name}"
        )
    finally:
        try:
            await session.kill()
        except Exception as e:
            logger.debug(f"Session kill cleanup: {e}")

        # Clean up temp profile directory
        if temp_dir and "browser-use-user-data-dir-" in temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug(f"Cleaned up temp dir: {temp_dir}")
            except Exception as e:
                logger.debug(f"Temp dir cleanup: {e}")

    cookies = storage_state.get("cookies", [])

    # Apply domain filter
    if domains:
        cookies = _filter_by_domains(cookies, domains)
        logger.info(f"Filtered to {len(cookies)} cookies for domains: {domains}")

    # Filter out session cookies if requested
    if not include_session_cookies:
        cookies = [c for c in cookies if c.get("expires", -1) > 0]
        logger.info(f"Filtered to {len(cookies)} persistent cookies")

    storage_state["cookies"] = cookies
    return storage_state


async def _export_cookies_from_running_chrome(
    cdp_url: str,
    domains: list[str] | None = None,
    include_session_cookies: bool = True,
) -> dict[str, Any]:
    """Extract cookies from an already-running Chrome with CDP enabled.

    Use this when profile-copy extraction returns 0 cookies due to
    App-Bound Encryption. Requires Chrome to have been launched with
    --remote-debugging-port=PORT.
    """
    from browser_use import BrowserSession

    session = BrowserSession(
        cdp_url=cdp_url,
    )

    try:
        await session.start()
        storage_state = await session.export_storage_state()
        cookie_count = len(storage_state.get("cookies", []))
        logger.info(f"Extracted {cookie_count} cookies from running Chrome at {cdp_url}")
    finally:
        try:
            await session.stop()
        except Exception as e:
            logger.debug(f"Session stop: {e}")

    cookies = storage_state.get("cookies", [])

    if domains:
        cookies = _filter_by_domains(cookies, domains)
        logger.info(f"Filtered to {len(cookies)} cookies for domains: {domains}")

    if not include_session_cookies:
        cookies = [c for c in cookies if c.get("expires", -1) > 0]
        logger.info(f"Filtered to {len(cookies)} persistent cookies")

    storage_state["cookies"] = cookies
    return storage_state


async def export_cookies_async(
    profile: str | None = None,
    browser: str | None = None,
    domains: list[str] | None = None,
    output_path: str | Path | None = None,
    include_session_cookies: bool = True,
    cdp_export_url: str | None = None,
) -> dict[str, Any]:
    """Export cookies from a Chrome profile via CDP. Async version.

    Args:
        profile: Profile directory name (e.g. "Profile 5") or display name
                 (e.g. "Work"). None = auto-detect last-used Chrome profile.
        browser: Browser name filter (e.g. "Google Chrome", "Arc").
                 None = search all browsers.
        domains: Optional domain suffixes to filter (e.g. ["google.com"]).
        output_path: Where to write JSON. Default: ~/.secondself/storage_state.json
        include_session_cookies: Include session cookies (no expiry).
        cdp_export_url: If set, extract cookies from an already-running Chrome
                        at this CDP URL instead of launching a temp instance.

    Returns:
        storage_state dict: {"cookies": [...], "origins": []}
    """
    if cdp_export_url:
        logger.info(f"Exporting cookies from running Chrome at {cdp_export_url}")
        storage_state = await _export_cookies_from_running_chrome(
            cdp_export_url, domains, include_session_cookies
        )
    else:
        profile_info = resolve_profile(profile, browser)
        logger.info(
            f"Exporting cookies from {profile_info.browser} / "
            f"{profile_info.display_name} ({profile_info.directory})"
        )
        storage_state = await _export_cookies_cdp(
            profile_info, domains, include_session_cookies
        )

    # Write to file
    out = Path(output_path) if output_path else DEFAULT_OUTPUT
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = out.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(storage_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.rename(out)

    cookie_count = len(storage_state.get("cookies", []))
    logger.info(f"Exported {cookie_count} cookies to {out}")
    return storage_state


def export_cookies(
    profile: str | None = None,
    browser: str | None = None,
    domains: list[str] | None = None,
    output_path: str | Path | None = None,
    include_session_cookies: bool = True,
    cdp_export_url: str | None = None,
) -> dict[str, Any]:
    """Export cookies from a Chrome profile via CDP. Synchronous wrapper.

    See export_cookies_async() for full documentation.
    """
    return asyncio.run(
        export_cookies_async(
            profile, browser, domains, output_path,
            include_session_cookies, cdp_export_url,
        )
    )
