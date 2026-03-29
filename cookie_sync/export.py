"""Export cookies from Chrome's SQLite DB on macOS with Keychain decryption."""

import json
import logging
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)

CHROME_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
# Chrome timestamps are microseconds since 1601-01-01 00:00:00 UTC
CHROME_EPOCH_OFFSET = 11644473600
DEFAULT_OUTPUT = Path.home() / ".secondself" / "storage_state.json"


def get_chrome_profiles() -> dict[str, str]:
    """Return {directory_name: display_name} for all Chrome profiles."""
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


def get_decryption_key() -> bytes:
    """Get the AES-128-CBC key for Chrome cookie decryption on macOS.

    Reads the password from macOS Keychain ("Chrome Safe Storage"),
    then derives the 16-byte AES key via PBKDF2-SHA1.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Keychain access timed out — is the Keychain locked?")

    if result.returncode != 0:
        raise RuntimeError(
            f"Keychain access failed (code {result.returncode}): {result.stderr.strip()}\n"
            "You may need to click 'Allow' in the Keychain dialog."
        )

    password = result.stdout.strip().encode("utf-8")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1003,
    )
    return kdf.derive(password)


def decrypt_cookie_value(encrypted_value: bytes, key: bytes, db_version: int = 24) -> Optional[str]:
    """Decrypt a Chrome cookie value.

    Values prefixed with b'v10' are AES-128-CBC encrypted.
    DB version 24+ prepends a 32-byte SHA256 domain hash to the plaintext.
    Returns None on decryption failure, empty string for legitimately empty values.
    """
    if not encrypted_value:
        return ""

    # Unencrypted value
    if not encrypted_value.startswith(b"v10"):
        try:
            return encrypted_value.decode("utf-8")
        except UnicodeDecodeError:
            return encrypted_value.decode("latin-1")

    # Strip the 3-byte version prefix
    ciphertext = encrypted_value[3:]
    if len(ciphertext) == 0:
        return ""

    iv = b" " * 16  # 16 bytes of 0x20 (space)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()

    try:
        padded = decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as e:
        logger.warning(f"Cookie decryption failed: {e}")
        return None

    # Remove PKCS7 padding
    if padded:
        pad_len = padded[-1]
        if 1 <= pad_len <= 16 and padded[-pad_len:] == bytes([pad_len]) * pad_len:
            padded = padded[:-pad_len]

    # DB version 24+: first 32 bytes are a SHA256 hash of the domain (integrity check)
    if db_version >= 24:
        padded = padded[32:]

    try:
        return padded.decode("utf-8")
    except UnicodeDecodeError:
        return padded.decode("latin-1")


def chrome_time_to_unix(chrome_utc: int) -> float:
    """Convert Chrome timestamp (microseconds since 1601-01-01) to Unix epoch seconds.

    Returns -1 for session cookies (chrome_utc == 0).
    """
    if chrome_utc == 0:
        return -1
    return (chrome_utc / 1_000_000) - CHROME_EPOCH_OFFSET


def samesite_to_str(val: int) -> str:
    """Map Chrome SQLite samesite integer to string."""
    return {0: "None", 1: "Lax", 2: "Strict"}.get(val, "Lax")


def _build_domain_filter(domains: list[str]) -> tuple[str, list[str]]:
    """Build a SQL WHERE clause for domain suffix matching.

    Chrome stores host_key as ".google.com" (with leading dot) or "google.com".
    We match both forms for each requested domain.
    """
    conditions = []
    params = []
    for domain in domains:
        domain = domain.lstrip(".")
        conditions.append("(host_key = ? OR host_key = ? OR host_key LIKE ?)")
        params.extend([domain, f".{domain}", f"%.{domain}"])
    return " AND (" + " OR ".join(conditions) + ")", params


def export_cookies(
    profile: str | None = None,
    domains: list[str] | None = None,
    output_path: str | Path | None = None,
    include_session_cookies: bool = True,
) -> dict[str, Any]:
    """Export cookies from Chrome's SQLite DB to Playwright storage_state format.

    Args:
        profile: Chrome profile directory name (e.g. "Profile 5").
                 None = auto-detect last-used profile.
        domains: Optional domain suffixes to filter (e.g. ["google.com"]).
                 None = export all cookies.
        output_path: Where to write JSON. Default: ~/.secondself/storage_state.json
        include_session_cookies: Include session cookies (expires=0).

    Returns:
        storage_state dict: {"cookies": [...], "origins": []}
    """
    if profile is None:
        profile = get_default_profile()
        logger.info(f"Auto-detected Chrome profile: {profile}")

    cookies_db = CHROME_DIR / profile / "Cookies"
    if not cookies_db.exists():
        raise FileNotFoundError(f"Cookies DB not found at {cookies_db}")

    logger.info(f"Reading cookies from {cookies_db}")

    # Get decryption key from Keychain
    key = get_decryption_key()
    logger.info("Got decryption key from Keychain")

    # Open DB in read-only mode (safe while Chrome is running).
    # Use text_factory=bytes so encrypted_value (BLOB) isn't decoded as UTF-8.
    conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True)
    conn.text_factory = bytes

    # Check DB version — v24+ prepends a 32-byte SHA256 domain hash to encrypted values
    db_version_row = conn.execute('SELECT value FROM meta WHERE key = "version"').fetchone()
    db_version = int(db_version_row[0]) if db_version_row else 0
    logger.debug(f"Cookie DB version: {db_version}")

    # Column indices for the query below
    COL_HOST_KEY = 0
    COL_NAME = 1
    COL_VALUE = 2
    COL_ENCRYPTED_VALUE = 3
    COL_PATH = 4
    COL_EXPIRES_UTC = 5
    COL_IS_SECURE = 6
    COL_IS_HTTPONLY = 7
    COL_HAS_EXPIRES = 8
    COL_IS_PERSISTENT = 9
    COL_SAMESITE = 10

    try:
        query = """
            SELECT host_key, name, value, encrypted_value, path,
                   expires_utc, is_secure, is_httponly, has_expires,
                   is_persistent, samesite
            FROM cookies
        """
        params: list[str] = []

        # Apply domain filter
        where_parts = []
        if domains:
            domain_clause, domain_params = _build_domain_filter(domains)
            where_parts.append(domain_clause.lstrip(" AND "))
            params.extend(domain_params)

        # Filter expired cookies
        now_chrome = int((time.time() + CHROME_EPOCH_OFFSET) * 1_000_000)
        where_parts.append(f"(expires_utc = 0 OR expires_utc > {now_chrome})")

        if not include_session_cookies:
            where_parts.append("is_persistent = 1")

        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

    finally:
        conn.close()

    logger.info(f"Found {len(rows)} cookies in DB")

    def _decode(val: bytes | str) -> str:
        """Decode bytes to str, passthrough if already str."""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return val

    # Decrypt and convert to Playwright format
    cookies = []
    decryption_failures = 0

    for row in rows:
        # Prefer plaintext value, fall back to decrypting encrypted_value
        raw_value = row[COL_VALUE]
        value = _decode(raw_value) if raw_value else ""
        if not value and row[COL_ENCRYPTED_VALUE]:
            decrypted = decrypt_cookie_value(bytes(row[COL_ENCRYPTED_VALUE]), key, db_version)
            if decrypted is None:
                decryption_failures += 1
                continue
            value = decrypted

        expires = chrome_time_to_unix(row[COL_EXPIRES_UTC])

        cookie: dict[str, Any] = {
            "name": _decode(row[COL_NAME]),
            "value": value,
            "domain": _decode(row[COL_HOST_KEY]),
            "path": _decode(row[COL_PATH]),
            "httpOnly": bool(row[COL_IS_HTTPONLY]),
            "secure": bool(row[COL_IS_SECURE]),
        }

        # Only set expires for persistent cookies (omit for session cookies)
        if expires > 0:
            cookie["expires"] = expires

        # Only set sameSite if explicitly specified
        samesite = row[COL_SAMESITE]
        if isinstance(samesite, int) and samesite >= 0:
            cookie["sameSite"] = samesite_to_str(samesite)

        cookies.append(cookie)

    if decryption_failures:
        logger.warning(f"Failed to decrypt {decryption_failures} cookies")

    storage_state = {"cookies": cookies, "origins": []}

    # Write to file
    out = Path(output_path) if output_path else DEFAULT_OUTPUT
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(storage_state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(out)

    logger.info(f"Exported {len(cookies)} cookies to {out}")
    return storage_state
