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

## Live System

The identity pipeline feeds a live digital twin that controls a macOS desktop.

```
PRIMARY SESSION (you)                    SECONDSELF SESSION (background)

 SecondSelf.app (SwiftUI notch app)      agent-server :8421
   ├─ orchestrator :8420                   ├─ MJPEG desktop stream
   │   ├─ Claude API (Sonnet 4)            ├─ Desktop tools (click, type, etc.)
   │   └─ Tool routing                     └─ Quartz screen capture
   ├─ VNC PiP (live desktop feed)
   └─ Chat (SSE streaming)              Chrome :9222 (CDP for browser-use)
                                         Vine Server :5901 (optional VNC)
```

### Quick Start (already provisioned)

```bash
# 1. Launch the app (starts orchestrator automatically)
cd SecondSelf && swift build && swift run

# 2. Cmd+Shift+T to toggle the chat panel
# 3. Talk to your twin
```

### First-Time Setup

```bash
# 1. Provision the secondself user account and services
./setup/provision.sh

# 2. Switch to secondself user session (click user icon in menu bar)
#    Grant Screen Recording to python3:
python3 -c "import Quartz; ref = Quartz.CGWindowListCreateImage(Quartz.CGRectInfinite, Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault); print(ref)"
#    Click Allow when macOS prompts, then switch back to your account

# 3. Restart agent-server to pick up the permission
./setup/restart-agent.sh

# 4. Verify everything works
./setup/smoke-test.sh
```

### Common Commands

| Command | What it does |
|---------|-------------|
| `cd SecondSelf && swift build && swift run` | Launch the app |
| `./setup/smoke-test.sh` | Test all services |
| `./setup/restart-agent.sh` | Restart agent-server (copies latest code) |
| `./setup/update-agent-server.sh` | Update agent-server code + restart |
| `open -a TigerVNC --args localhost:5901` | View secondself's desktop |
| `curl -s http://localhost:8421/health \| python3 -m json.tool` | Agent server health |
| `sudo kill $(sudo lsof -ti :8420) 2>/dev/null` | Kill stale orchestrator |

### Environment Variables

Create a `.env` file:

```
ANTHROPIC_API_KEY=
TAVILY_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-20250514
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

### Ports

| Port | Service | Session |
|------|---------|---------|
| 8420 | Orchestrator (Claude API bridge) | Primary (launched by app) |
| 8421 | Agent Server (desktop tools + MJPEG stream) | secondself (LaunchAgent) |
| 5901 | Vine Server VNC (optional) | secondself (LaunchAgent) |
| 9222 | Chrome DevTools Protocol | secondself (LaunchAgent) |

## Identity Pipeline

### Full pipeline

```bash
python main.py
```

Runs all layers: Gmail fetch, Tavily search, email cleaning, all analyzers in parallel, identity build, event extraction, calendar fetch, and preferences synthesis.

### Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Run pipeline without writing to `~/.secondself/` |
| `--no-cache` | Bypass all caches and re-fetch from APIs |
| `--tavily-only` | Skip Gmail, build identity from Tavily web search only |
| `--memory-only` | Skip Gmail fetch and Layer 1 analyzers, only refresh Layer 2 + 4 |
| `--verbose` | Enable DEBUG logging |

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

## License

Private.
