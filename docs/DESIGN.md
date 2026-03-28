# Design: Second Self — Hackathon MVP

Updated: 2026-03-28
Branch: main
Repo: second-self
Status: APPROVED + IN PROGRESS
Team: Johnathan + Mac

## Problem Statement

A macOS "digital twin" that creates a second user session running simultaneously, controlled by AI agents, visible to the primary user through a notch-resident UI. Someone walks up to the booth, downloads the app, types their name, and watches their twin come to life.

## Demo Flow

1. Person walks up to booth
2. Downloads app from landing page (GoDaddy) — unsigned, needs Gatekeeper bypass
3. App creates secondself user, provisions everything
4. Person types their name → Tavily profiles them instantly
5. Twin desktop wakes up shaped around them (anticipatory twin)
6. Person gives a command → watches the twin execute it in VNC
7. "Whoa" moment

## Team / Work Split

| Owner | Area | What |
|-------|------|------|
| **Mac** | Local plumbing | VNC (Vine Server :5901 + TigerVNC), Fast User Switching, computer use execution |
| **Mac** | UI/UX | Notch menubar app (Swift/SwiftUI), input pill, VNC viewer embed |
| **Both** | MCP connectors | Google Workspace, Notion, Slack integrations for the digital twin |
| **Both** | Onboarding flow | Build an accurate second self: profiling, style fingerprinting, cookie cloning |
| **Both** | Memory layer | Persistent context about who the user is, what they've done, how they think |

## What's Proven (Phase 1 Complete)

- Fast User Switching works on Tahoe (26.x) — two WindowServer processes
- VNC works: Vine Server on :5901, TigerVNC client (Apple's Screen Sharing doesn't work for background sessions on localhost)
- Agent Server runs in secondself's GUI session (:8421)
- PyAutoGUI controls mouse/keyboard on secondself's display
- `open -a` commands launch apps without AppleScript permissions
- Dedalus Labs is the LLM brain (OpenAI-compatible API, not computer use)
- API keys: Dedalus + Tavily configured in `.env`

---

## Architecture (Current)

```
PRIMARY SESSION                         SECOND SELF SESSION
─────────────────                       ─────────────────────

┌─────────────────────┐                 ┌──────────────────────────┐
│  Menubar App (Mac)  │                 │  Agent Server (Python)   │
│  Swift/SwiftUI      │                 │  port 8421               │
│  ┌───────────────┐  │                 │                          │
│  │ Input Pill    │──┼──HTTP :8420──►  │  BROWSER AGENT           │
│  └───────────────┘  │                 │  agent-browser CLI       │
│  ┌───────────────┐  │                 │  /browser/goto           │
│  │ TigerVNC      │◄─┼──VNC :5901──── │  /browser/click @ref     │
│  │ (live view)   │  │                 │  /browser/fill @ref      │
│  └───────────────┘  │                 │  /browser/snapshot       │
└────────┬────────────┘                 │                          │
         │                              │  DESKTOP AGENT           │
         ▼                              │  PyAutoGUI               │
┌─────────────────────┐                 │  /tool/open_app          │
│  Orchestrator       │                 │  /tool/click (pixels)    │
│  (Python, port 8420)│                 │  /tool/type              │
│                     │                 │  /tool/hotkey            │
│  ┌───────────────┐  │  Dedalus API   │                          │
│  │ Task Router   │──┼────────────►   │  MCP AGENT               │
│  │ (browser vs   │  │  LLM brain    │  Google, Notion, Slack    │
│  │  desktop vs   │◄─┼────────────   │  /mcp/google/*           │
│  │  mcp)         │  │  tool calls   │  /mcp/notion/*           │
│  └───────────────┘  │                │  /mcp/slack/*            │
│                     │                │                          │
│  ┌───────────────┐  │                │  Chrome visible in VNC   │
│  │ Memory Layer  │  │                │  Vine Server daemon      │
│  │ (user context)│  │                │  agent-browser daemon    │
│  └───────────────┘  │                └──────────────────────────┘
│                     │
│  ┌───────────────┐  │
│  │ Tavily        │  │
│  │ Profiler      │  │
│  └───────────────┘  │
└─────────────────────┘
```

---

## Three Agent Types

The orchestrator routes tasks to the right agent based on what needs to happen.

### 1. Browser Agent (agent-browser)

**What:** Controls Chrome via Playwright with ref-based element selection. No pixel clicking, no screenshots for navigation. Fast and reliable.

**When:** Any web task. Research, search, fill forms, read pages, navigate between sites.

**How:** agent-browser CLI runs as a daemon in secondself's session. The Agent Server shells out to it. Chrome window is visible in VNC so the user watches it work.

**Tools:**
```
browser_goto(url)          — navigate to URL
browser_click(ref)         — click element by accessibility ref
browser_fill(ref, text)    — fill input field
browser_snapshot()         — get page structure with element refs
browser_text()             — get page text content
browser_press(key)         — press keyboard key (Enter, Tab, etc.)
```

### 2. Desktop Agent (PyAutoGUI)

**What:** Controls mouse, keyboard, and desktop-level interactions. Opens apps, switches windows, takes screenshots of the full desktop.

**When:** Non-browser tasks. Opening apps, arranging windows, interacting with native macOS apps (Notes, Finder, Calendar), desktop-level UI.

**How:** PyAutoGUI runs in secondself's GUI session context. Must be started from within the GUI session (not via SSH or sudo).

**Tools:**
```
open_app(name)             — open any macOS app
click(x, y)                — click at pixel coordinates
type_text(text)            — type on keyboard
hotkey(keys)               — keyboard shortcut (cmd+t, etc.)
scroll(dy)                 — scroll up/down
move_mouse(x, y)           — move cursor
screenshot()               — capture full desktop (slow, use sparingly)
```

### 3. MCP Agent (API-level, no UI)

**What:** Interacts with cloud services directly via their APIs, not through the browser UI. Faster, more reliable, no visual interaction needed.

**When:** Reading/writing to Google Workspace, Notion, Slack. Checking email, creating docs, posting messages. Any task where API access is faster than browser UI.

**How:** MCP (Model Context Protocol) servers connect the LLM to external services. Dedalus supports MCP servers natively. The twin uses the user's authenticated sessions.

**Tools (planned):**
```
google_search(query)       — search Google via API
google_docs_create(title)  — create a Google Doc
google_calendar_check()    — check today's calendar
notion_read(page_id)       — read a Notion page
notion_create(title, body) — create a Notion page
slack_send(channel, msg)   — send a Slack message
slack_read(channel)        — read recent Slack messages
```

**Auth approach:** Firebase to bypass Google Cloud Console "unverified" screen. Auth0 for identity. Copy user's OAuth tokens or cookies to secondself's session.

### Agent Router Logic

```python
def route_task(task: str, context: dict) -> str:
    """Decide which agent handles a task."""
    # If task involves a URL or web content → Browser Agent
    # If task involves a cloud service with MCP → MCP Agent (faster)
    # If task involves desktop apps or system actions → Desktop Agent
    # If unclear → ask LLM to classify, default to Browser Agent
```

The LLM (via Dedalus) can also chain agents: "Research quantum computing (browser) → create a summary doc (MCP/Notion or desktop/Notes) → message the team about it (MCP/Slack)."

---

## Onboarding Flow

The goal: within 60 seconds of typing your name, the system knows enough about you to be useful. Within 5 minutes, it feels like it's been watching you work for weeks.

### Tier 1: Instant Profile (seconds)

```
User types name
        │
        ▼
Tavily web search ──► structured profile JSON
  "Johnathan Mo professional background"
  "Johnathan Mo twitter LinkedIn github"
        │
        ▼
LLM summarizes ──► { name, title, company, interests[], bio }
        │
        ▼
Anticipatory twin setup ──► Chrome opens relevant tabs,
  Notes creates a task list, desktop looks personalized
```

This is what we demo at the booth. Fast, visual, impressive.

### Tier 2: Deep Profile (minutes, with user consent)

```
User grants access to:
  ├── Cookies ──► clone to secondself (Chrome profile copy)
  ├── Files ──► read access to Documents, Desktop, Downloads
  ├── Email ──► analyze writing style, extract contacts/projects
  ├── Twitter/social ──► analyze voice, interests, opinions
  └── Calendar ──► understand schedule, priorities, deadlines
        │
        ▼
Style Fingerprinting ──► { writing_style, vocabulary, tone,
  emoji_usage, formality_level, typical_greeting, sign_off }
        │
        ▼
Memory Layer populated with deep user context
```

### Tier 3: Continuous Learning (ongoing, post-hackathon)

The twin watches what the user does and learns patterns. RL-based improvement. Prime Intellect or Modal for training.

### Cookie Cloning (Tier 2)

Copy the user's Chrome cookies to secondself's Chrome profile so the twin is logged into the same services:

```bash
# Chrome cookies location
PRIMARY=~/Library/Application\ Support/Google/Chrome/Default/Cookies
SECOND=/Users/secondself/Library/Application\ Support/Google/Chrome/Default/Cookies

# Copy (Chrome must be closed in secondself session)
sudo cp "$PRIMARY" "$SECOND"
sudo chown secondself:staff "$SECOND"
```

This gives the twin access to Gmail, Google Docs, Notion, Slack, etc. without re-authenticating.

### File Permission Sharing

Grant secondself read access to the user's directories:

```bash
# Grant read access to specific dirs
chmod o+rx ~/Documents ~/Desktop ~/Downloads
# Or use ACLs for more granular control:
sudo chmod +a "secondself allow read,readattr,readextattr,readsecurity,list,search" ~/Documents
```

---

## Memory Layer

The memory layer is what makes the twin feel like it actually knows you, not just Googled you once.

### Architecture

```
┌─────────────────────────────────────────────┐
│               MEMORY LAYER                   │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ User Profile  │  │ Session Memory       │ │
│  │ (persistent)  │  │ (current session)    │ │
│  │               │  │                      │ │
│  │ name          │  │ current_task         │ │
│  │ title         │  │ open_tabs[]          │ │
│  │ company       │  │ recent_actions[]     │ │
│  │ interests[]   │  │ conversation[]       │ │
│  │ writing_style │  │ errors_encountered[] │ │
│  │ contacts[]    │  │ files_accessed[]     │ │
│  │ projects[]    │  │                      │ │
│  │ preferences{} │  │                      │ │
│  └──────────────┘  └──────────────────────┘ │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Task History  │  │ Style Model          │ │
│  │ (what twin    │  │ (how user writes)    │ │
│  │  has done)    │  │                      │ │
│  │               │  │ tone: casual         │ │
│  │ task_log[]    │  │ emoji: rare          │ │
│  │ success_rate  │  │ greeting: "hey"      │ │
│  │ avg_duration  │  │ formality: low       │ │
│  │ common_tasks  │  │ vocabulary: tech     │ │
│  └──────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────┘
```

### Storage (MVP)

For hackathon: JSON files on disk. No database needed.

```
/Users/secondself/second-self/memory/
├── profile.json          # User profile (from Tavily + enrichment)
├── session.json          # Current session state
├── task_history.json     # Log of all tasks executed
└── style.json            # Writing style model
```

The orchestrator reads/writes these files. Every agent action updates session memory. The LLM gets relevant memory injected into its system prompt so it has context.

### Memory in the System Prompt

```python
def build_system_prompt(memory: dict) -> str:
    return f"""You are {memory['profile']['name']}'s digital twin.

You know:
- They work as {memory['profile']['title']} at {memory['profile']['company']}
- Their interests: {', '.join(memory['profile']['interests'])}
- Their writing style: {memory['style']['tone']}, {memory['style']['formality']}
- Current session: {memory['session']['current_task']}
- Recent actions: {memory['session']['recent_actions'][-5:]}

Act as them. Use their voice. Prioritize what matters to them."""
```

### Post-Hackathon: MongoDB Atlas

Persistent storage across sessions. Vector search for semantic memory retrieval. User profiles, task history, embeddings of past interactions.

---

## Tech Stack (Updated)

| Component | Technology | Owner | Status |
|-----------|-----------|-------|--------|
| Menubar app | Swift + SwiftUI + AppKit | Mac | Not started |
| VNC viewer | TigerVNC (Vine Server on :5901) | Mac | **Working** |
| Agent Server | Python HTTP on :8421 | Both | **Working** |
| Orchestrator | Python HTTP on :8420 | Both | Built, needs testing |
| Browser agent | agent-browser (Vercel Labs) | Both | Next step |
| Desktop agent | PyAutoGUI | Both | **Working** |
| MCP agent | Dedalus MCP servers | Both | Not started |
| LLM brain | Dedalus Labs API (OpenAI-compat) | Both | Configured |
| Web profiling | Tavily API | Both | Configured |
| Memory layer | JSON files (MVP), MongoDB Atlas (later) | Both | Not started |
| Auth | Auth0 | Both | Not started |
| Session mgmt | sysadminctl + launchctl | Mac | **Working** |
| Landing page | GoDaddy | Mac | Not started |

## What's CUT for MVP

- RL training (Prime Intellect/Modal) — post-hackathon
- Lava gateway — post-hackathon
- MongoDB Atlas — post-hackathon (JSON files for now)
- Style fingerprinting — Tier 2 onboarding, only if time
- File permission sharing — Tier 2, only if time
- Cookie cloning — Tier 2, only if time
- App notarization — unsigned, use `xattr -cr` bypass

## Known Issues / Learnings from Phase 1

1. **ARDAgent kickstart is dead** on macOS 12.1+. Screen Sharing must be enabled via GUI.
2. **`vnc://localhost` connects to YOUR session**, not the background user. Use Vine Server on :5901 + TigerVNC.
3. **Apple's Screen Sharing app doesn't work** with Vine Server. TigerVNC does.
4. **`su -l` can't run GUI commands.** Use `launchctl asuser` or start processes from within the GUI session.
5. **PyAutoGUI must run from the GUI session** — starting via SSH or sudo runs it against the wrong display.
6. **Dedalus is NOT computer use** — it's an MCP platform / LLM gateway. Use it as the brain, build your own tools.
7. **Fast User Switching on Tahoe is janky** — may need multiple attempts to switch.

## Success Criteria

- [ ] Full demo loop: name → profile → twin setup → command → watch it work (2-3 min)
- [ ] Demo succeeds 8/10 cold runs with different names
- [ ] Browser agent works (agent-browser controls Chrome visibly in VNC)
- [ ] At least one MCP integration works (Google, Notion, or Slack)
- [ ] Memory layer persists across commands within a session
- [ ] No visible crashes during demo
