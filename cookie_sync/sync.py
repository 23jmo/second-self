"""Cookie sync CLI — export from user's Chrome, import to secondself Chrome.

Usage:
    python -m cookie_sync.sync                              # Full sync (auto-detect profile)
    python -m cookie_sync.sync --list-profiles              # Show available profiles
    python -m cookie_sync.sync --profile Work               # Sync from "Work" profile
    python -m cookie_sync.sync --profile "Profile 4"        # Sync by directory name
    python -m cookie_sync.sync --browser Arc --profile School
    python -m cookie_sync.sync --domains google.com,github.com
    python -m cookie_sync.sync --export-only                # Just save JSON
    python -m cookie_sync.sync --import-only                # Just push existing JSON
    python -m cookie_sync.sync --no-clear                   # Merge, don't replace
    python -m cookie_sync.sync --verbose                    # Debug logging
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from cookie_sync.export import (
    export_cookies,
    get_all_profiles,
    get_default_profile,
)
from cookie_sync.import_cookies import import_cookies_sync

DEFAULT_STATE_PATH = Path.home() / ".secondself" / "storage_state.json"
CDP_URL = "http://localhost:9222"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Chrome cookies to secondself browser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--domains", type=str, default=None,
        help="Comma-separated domain filter (e.g. google.com,github.com)",
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help="Profile name or directory (e.g. 'Work', 'Profile 5', 'columbia.edu')",
    )
    parser.add_argument(
        "--browser", type=str, default=None,
        help="Browser name to disambiguate profiles (e.g. 'Google Chrome', 'Arc')",
    )
    parser.add_argument(
        "--list-profiles", action="store_true",
        help="List available browser profiles and exit",
    )
    parser.add_argument(
        "--export-only", action="store_true",
        help="Only export cookies to JSON, skip CDP import",
    )
    parser.add_argument(
        "--import-only", action="store_true",
        help="Only import from existing JSON, skip export",
    )
    parser.add_argument(
        "--output", type=str, default=str(DEFAULT_STATE_PATH),
        help=f"Output path for storage_state.json (default: {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--cdp-url", type=str, default=CDP_URL,
        help=f"CDP URL for secondself Chrome (default: {CDP_URL})",
    )
    parser.add_argument(
        "--cdp-export", type=str, default=None, metavar="URL",
        help="Export cookies from an already-running Chrome at this CDP URL "
             "(e.g. http://localhost:9224). Use when profile-copy returns 0 cookies "
             "due to App-Bound Encryption.",
    )
    parser.add_argument(
        "--no-clear", action="store_true",
        help="Don't clear existing cookies before import (merge mode)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # List profiles mode
    if args.list_profiles:
        profiles = get_all_profiles()
        if not profiles:
            print("No browser profiles found.", file=sys.stderr)
            return 1

        try:
            default = get_default_profile()
        except Exception:
            default = None

        # Group by browser
        by_browser: dict[str, list] = {}
        for p in profiles:
            by_browser.setdefault(p.browser, []).append(p)

        idx = 1
        for browser, browser_profiles in by_browser.items():
            print(f"\n{browser}:")
            for p in browser_profiles:
                marker = " (last used)" if (
                    browser == "Google Chrome" and p.directory == default
                ) else ""
                print(f"  {idx}. {p.display_name} ({p.directory}){marker}")
                idx += 1
        return 0

    domains = [d.strip() for d in args.domains.split(",")] if args.domains else None

    start = time.time()

    # Export step
    if not args.import_only:
        try:
            state = export_cookies(
                profile=args.profile,
                browser=args.browser,
                domains=domains,
                output_path=args.output,
                cdp_export_url=args.cdp_export,
            )
            cookie_count = len(state.get("cookies", []))
            print(f"Exported {cookie_count} cookies to {args.output}")
            if cookie_count == 0:
                print(
                    "\nWarning: 0 cookies exported. This can happen when:\n"
                    "  - The profile has no cookies\n"
                    "  - Chrome's App-Bound Encryption prevents extraction from copied profiles\n"
                    "\nTo work around App-Bound Encryption:\n"
                    "  1. Quit Chrome\n"
                    '  2. Relaunch: open -a "Google Chrome" --args --remote-debugging-port=9224\n'
                    "  3. Run: python -m cookie_sync.sync --cdp-export http://localhost:9224\n"
                    "\nOr try a different profile: python -m cookie_sync.sync --list-profiles",
                    file=sys.stderr,
                )
        except ValueError as e:
            print(f"Profile error: {e}", file=sys.stderr)
            return 1
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Import step
    if not args.export_only:
        try:
            result = import_cookies_sync(
                storage_state_path=args.output,
                cdp_url=args.cdp_url,
                domains=domains,
                clear_existing=not args.no_clear,
            )
            print(f"Imported {result['imported']} cookies into Chrome at {args.cdp_url}")
            if result.get("cleared"):
                print("  (existing cookies were cleared first)")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except ConnectionError as e:
            print(f"Error connecting to Chrome CDP: {e}", file=sys.stderr)
            print("Is secondself Chrome running with --remote-debugging-port=9222?", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Import error: {e}", file=sys.stderr)
            return 1

    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
