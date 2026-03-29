# Second Self

A background pipeline that builds a multi-layered psychological and behavioral profile from your Gmail, Google Calendar, and web presence. The output becomes the "primer" for a digital twin agent that acts on your behalf.

## Architecture

Second Self builds a 6-layer memory system. This branch implements Layers 1-4:

```
Layer 1  identity.md         Who you are — role, voice, interests, behavioral patterns
Layer 2  preferences.md      How you work — schedule, tools, communication style, focus areas
Layer 2.5 relationships.json  Who you know — contact graph with closeness scores
Layer 3  (reserved)          Contextual memory (future)
Layer 4  episodic.md         What happened — timestamped life events extracted from email history
```

All profile files are written to `~/.secondself/` for consumption by the twin agent.

## Pipeline

```
Gmail OAuth ──> Fetch Emails ──> Clean ──> Analyze (parallel) ──> Build Profiles
                                             |
Google Auth ──> Calendar Fetch ─────────────┘
                                             |
              Tavily Search ─────────────────┘
```

### Analysis passes (Layer 1)

| Module | Input | Output |
|--------|-------|--------|
| `voice_analyzer` | Sent emails | Voice profile — tone, openers, sign-offs, code-switching |
| `topic_extractor` | All emails | Top 15 recurring topics with frequency and confidence |
| `behavior_analyzer` | All emails + threads | Reply speed, active hours, initiation ratio |
| `relationship_mapper` | All emails | Contact graph — inner circle, colleagues, acquaintances |
| `tavily_synthesizer` | Web search results | Public profile — role, company, social links |

### Layer 2: Preferences

`build/preferences_builder.py` synthesizes work preferences from behavior data, calendar events, topics, and relationships via an LLM call. Outputs schedule patterns, recurring commitments, focus areas, communication style, and inferred tools.

### Layer 4: Episodic Memory

`analyze/event_extractor.py` extracts life events (job changes, travel, education milestones) from email history using parallel per-year workers with `ProcessPoolExecutor`. Events are written to `episodic.md` with their original timestamps.

`utils/episodic_writer.py` provides a file-locked append API for the twin agent to record events at runtime.

## Project Structure

```
second-self/
├── main.py                        # Pipeline orchestrator
├── auth/
│   ├── firebase_auth.py           # Firebase token exchange
│   ├── gmail_auth.py              # Google credentials from access token
│   └── web_oauth.py               # FastAPI server for browser-based OAuth
├── fetch/
│   ├── gmail_fetch.py             # Gmail API fetch with 24h cache
│   ├── tavily_fetch.py            # Tavily web search (3 queries)
│   └── calendar_fetch.py          # Google Calendar fetch (90d past + 30d future)
├── clean/
│   └── email_cleaner.py           # HTML stripping, signature removal, deduplication
├── analyze/
│   ├── voice_analyzer.py          # Writing style analysis on sent emails
│   ├── topic_extractor.py         # Topic/interest extraction via LLM
│   ├── behavior_analyzer.py       # Response patterns and habits
│   ├── relationship_mapper.py     # Contact scoring and clustering
│   ├── tavily_synthesizer.py      # Public profile extraction via LLM
│   └── event_extractor.py         # Life event extraction via parallel LLM workers
├── build/
│   ├── identity_builder.py        # Assembles identity.md (Layer 1)
│   └── preferences_builder.py     # Assembles preferences.md (Layer 2)
├── utils/
│   └── episodic_writer.py         # File-locked episodic memory writer (Layer 4)
├── static/
│   └── login.html                 # Google Identity Services auth page
├── output/                        # Local cache of all pipeline outputs
└── tests/                         # 430+ unit tests
```

## Setup

### Prerequisites

- Python 3.11+
- A Google Cloud project with Gmail API and Calendar API enabled
- A Google Cloud project with OAuth 2.0 client credentials
- Tavily API key
- Anthropic API key

### Installation

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file:

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8080
TAVILY_API_KEY=
ANTHROPIC_API_KEY=
USER_NAME=                # optional — auto-detected from Google sign-in
USER_EMAIL=               # optional — auto-detected from Google sign-in
```

## Usage

### Full pipeline

```bash
python main.py
```

Runs all layers: Gmail fetch, Tavily search, email cleaning, all analyzers in parallel, identity build, event extraction, calendar fetch, and preferences synthesis.

### Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Run pipeline without writing to `~/.secondself/`. Prints all outputs to stdout. |
| `--no-cache` | Bypass all caches and re-fetch from APIs. |
| `--tavily-only` | Skip Gmail entirely, build identity from Tavily web search only. |
| `--memory-only` | Skip Gmail fetch and Layer 1 analyzers. Only refresh Layer 2 + 4 (events, calendar, preferences). |
| `--verbose` | Enable DEBUG logging. |

### Examples

```bash
# First run — full pipeline
python main.py

# Quick refresh of preferences and events without re-fetching emails
python main.py --memory-only

# Preview what the pipeline would produce
python main.py --dry-run

# Rebuild from scratch, ignoring all caches
python main.py --no-cache
```

## Output

After a successful run:

```
~/.secondself/
├── identity.md          # Layer 1 — who you are
├── preferences.md       # Layer 2 — how you work
└── episodic.md          # Layer 4 — what happened
```

## Tests

```bash
python -m pytest tests/ -v
```

430+ unit tests covering all modules with mocked LLM and API calls.

## License

Private.
