# main.py
# Orchestrates the full Layer 1 identity pipeline:
#   1. Load .env
#   2. Gmail OAuth (auth/gmail_auth.py)
#   3. Tavily fetch (fetch/tavily_fetch.py)  — parallel with step 4
#   4. Gmail fetch (fetch/gmail_fetch.py)    — uses cache if fresh (<24h)
#   5. Email cleaning (clean/email_cleaner.py)
#   6. Analysis passes in parallel:
#        voice_analyzer, topic_extractor, behavior_analyzer,
#        relationship_mapper, tavily_synthesizer
#   7. Identity assembly (build/identity_builder.py)
#   8. Print summary: emails processed, top 3 topics, output path
#
# Flags:
#   --dry-run      run everything except writing the final identity.md
#   --no-cache     bypass email cache, re-fetch from Gmail
#   --tavily-only  skip Gmail entirely, build from Tavily results only
#   --verbose      set log level to DEBUG

import argparse
import logging
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Self — Layer 1 Identity Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline without writing identity.md")
    parser.add_argument("--no-cache", action="store_true", help="Bypass email cache and re-fetch from Gmail")
    parser.add_argument("--tavily-only", action="store_true", help="Skip Gmail, build from Tavily results only")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    load_dotenv()


if __name__ == "__main__":
    main()
