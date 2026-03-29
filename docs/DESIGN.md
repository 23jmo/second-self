# Design: Second Self — Hackathon MVP

Updated: 2026-03-28
Branch: jym2117/tab-54-core-app-notch-ui-orchestration-and-vnc-on
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

## Architecture (Current)

```
PRIMARY SESSION                         SECOND SELF SESSION
─────────────────                       ─────────────────────

┌──────────────────────────────┐
│  SecondSelf.app (SwiftUI)    │
│                              │
│  ┌────────────────────────┐  │
│  │ NotchOverlay (NSPanel)  │  │
│  │ S1: Twin peek           │  │
│  │ S2: Expanded + Twin     │  │
│  │ S3: Full chat + VNC PiP │  │
│  └────────────────────────┘  │
│                              │
│  ┌────────────────────────┐  │
│  │ ChatViewModel           │  │          ┌──────────────────────┐
│  │ SSE client ──────────────┼─────────► │ Orchestrator (:8420)  │
│  │ Messages, Twin state    │  │ ◄─SSE── │ FastAPI + uvicorn     │
│  │ Typewriter animation    │  │          │                      │
│  └────────────────────────┘  │          │ POST /chat (SSE)      │
│                              │          │ POST /command          │
│  ┌────────────────────────┐  │          │ POST /profile          │
│  │ VNCPipView (native)    │  │          │ POST /demo             │
│  │ MJPEG ◄──────────────────┼───────── │ POST /reset            │
│  │ from :8421/stream      │  │          │ GET  /health           │
│  │ Quartz CoreGraphics    │  │          │ GET  /status           │
│  └────────────────────────┘  │          │                      │
│                              │          │ Job State Machine:     │
│  Global Hotkey: Cmd+Shift+T  │          │ idle→thinking→working  │
│  Audio: task/complete sounds │          │ →complete→idle         │
└──────────────────────────────┘          │ Message queue when busy│
                                          └──────────┬───────────┘
                                                     │ HTTP
                                                     ▼
                                          ┌──────────────────────┐
                                          │ Agent Server (:8421)  │
                                          │ ThreadingHTTPServer   │
                                          │ runs in secondself    │
                                          │ GUI session           │
                                          │                      │
                                          │ BROWSER (browser-use) │
                                          │ /browser/goto         │
                                          │ /browser/click        │
                                          │ /browser/fill         │
                                          │ /browser/snapshot     │
                                          │                      │
                                          │ DESKTOP (PyAutoGUI)   │
                                          │ /tool/click           │
                                          │ /tool/type            │
                                          │ /tool/hotkey          │
                                          │ /tool/open_app        │
                                          │                      │
                                          │ STREAM (Quartz CG)    │
                                          │ GET /stream (MJPEG)   │
                                          │ Main-thread capture   │
                                          │ ~10fps, JPEG q60      │
                                          │                      │
                                          │ Chrome visible in VNC │
                                          │ Vine Server :5901     │
                                          └──────────────────────┘
```

## Key Components

### SecondSelf.app (SwiftUI, macOS)

The notch-resident UI. No dock icon (LSUIElement). Built with Swift Package Manager.

- **NotchOverlayController** — NSPanel at statusBar+1 level, non-activating, 3 states (collapsed/expanded/fullChat) with spring animations
- **ChatView** — ScrollView + LazyVStack of messages, auto-scroll, VNC PiP overlay
- **ChatViewModel** — SSE client connecting to POST /chat, parses state/token/tool_call/tool_result/error events, manages Twin state machine
- **TwinCharacterView** — Animated mascot with 5 states (idle/thinking/working/complete/error), procedural breathing/bobbing/wiggling
- **VNCPipView** — Native URLSession MJPEG parser (no WKWebView), reads JPEG frames from /stream, olive-green glow when working
- **AudioManager** — System sounds for task start, completion, typing clicks
- **Global Hotkey** — Cmd+Shift+T toggles panel via NSEvent global monitor

Auto-launches the orchestrator as a subprocess on app start. Agent-server runs separately in secondself's session.

### Orchestrator (FastAPI, port 8420)

The brain. Runs in the primary session. Bridges UI ↔ LLM ↔ Agent Server.

- **FastAPI + uvicorn** — async, CORS middleware, SSE streaming
- **Job state machine** — idle/thinking/working/complete/error with asyncio.Lock
- **POST /chat** — SSE endpoint streaming state, token, tool_call, tool_result, error, ping events
- **Message queue** — when busy, queued messages auto-process after current job completes
- **POST /reset** — clears job state, conversation history, profile cache (for demo transitions)
- **Dedalus API** — OpenAI-compatible, stream=true for token streaming
- **Tavily API** — web profiling for instant stranger profiles
- **27 passing pytest tests** covering state machine, SSE, error handling

### Agent Server (ThreadingHTTPServer, port 8421)

Runs in secondself's GUI session via `launchctl asuser`. Controls the second desktop.

- **MJPEG stream** — Quartz CoreGraphics capture on main thread (~10fps), served to worker threads via shared buffer with threading.Lock
- **Browser tools** — browser-use CLI via CDP (Chrome on :9222)
- **Desktop tools** — PyAutoGUI for mouse, keyboard, app launching
- **Main-thread architecture** — HTTP server runs in background thread, screenshot capture runs on main thread (Cocoa APIs require main thread)

## Three Agent Types

### 1. Browser Agent (browser-use)

Controls Chrome via Playwright with ref-based element selection. CLI commands: goto, click, fill, snapshot, screenshot, text, press. Chrome window visible in VNC/MJPEG stream.

### 2. Desktop Agent (PyAutoGUI)

Controls mouse, keyboard, desktop-level interactions. Opens apps, switches windows, types text. Must run from within the GUI session.

### 3. MCP Agent (API-level, planned)

Direct API access to Google Workspace, Notion, Slack. Not yet implemented.

## SSE Event Protocol

The orchestrator streams events to the SwiftUI app via Server-Sent Events:

```
event: state
data: {"state": "thinking"}

event: token
data: {"text": "I'll search for..."}

event: tool_call
data: {"tool": "browser_goto", "args": {"url": "..."}, "step": 1}

event: tool_result
data: {"tool": "browser_goto", "result": {"status": "ok"}, "step": 1}

event: state
data: {"state": "complete"}

event: error
data: {"message": "Twin had trouble connecting"}

event: ping
data: {}
```

## Tech Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| Notch app | Swift + SwiftUI + AppKit (NSPanel) | **Built** |
| VNC viewer | Native MJPEG parser (URLSession) | **Built** |
| Orchestrator | FastAPI + uvicorn on :8420 | **Built** |
| Agent Server | Python ThreadingHTTPServer on :8421 | **Built** |
| Screen capture | Quartz CoreGraphics (main thread) | **Built** |
| Browser agent | browser-use CLI via CDP | **Built** |
| Desktop agent | PyAutoGUI | **Built** |
| LLM brain | Dedalus Labs API (OpenAI-compat) | Configured |
| Web profiling | Tavily API | Configured |
| VNC server | Vine Server on :5901 | **Working** |
| Session mgmt | sysadminctl + launchctl | **Working** |
| Tests | pytest (27 tests) | **Passing** |
| MCP agent | Google, Notion, Slack | Not started |
| Memory layer | JSON files (MVP) | Not started |
| Landing page | GoDaddy | Not started |

## File Structure

```
second-self/
├── SecondSelf/                    # SwiftUI macOS app
│   ├── Package.swift
│   ├── SecondSelfApp.swift        # Entry point, subprocess launcher
│   ├── NotchOverlayController.swift
│   ├── Views/
│   │   ├── ChatView.swift
│   │   ├── ChatInputBar.swift
│   │   ├── TwinMessageBubble.swift
│   │   ├── UserMessageBubble.swift
│   │   ├── ToolCallPill.swift
│   │   ├── VNCPipView.swift       # Native MJPEG parser
│   │   └── TwinCharacterView.swift
│   ├── ViewModels/
│   │   └── ChatViewModel.swift    # SSE client + state
│   ├── Models/
│   │   ├── ChatMessage.swift
│   │   ├── TwinState.swift
│   │   └── SSEParser.swift
│   ├── Utilities/
│   │   └── AudioManager.swift
│   └── Assets.xcassets/Colors/    # 9 design system colors
├── orchestrator/
│   ├── server.py                  # FastAPI orchestrator
│   ├── requirements.txt           # fastapi, uvicorn, httpx, pytest
│   └── test_server.py             # 27 tests
├── agent-server/
│   ├── server.py                  # ThreadingHTTPServer + Quartz capture
│   └── screenshot.py              # Standalone screenshot utility
├── setup/
│   ├── provision.sh               # One-shot setup for secondself user
│   ├── update-agent-server.sh     # Copy updated code to secondself
│   ├── ai.secondself.agent.plist  # LaunchAgent for agent-server
│   ├── ai.secondself.orchestrator.plist
│   ├── ai.secondself.vine.plist   # LaunchAgent for Vine VNC
│   └── ai.secondself.chrome.plist # LaunchAgent for Chrome CDP
├── docs/
│   ├── DESIGN.md                  # This file
│   └── SPEC-agent-browser-integration.md
├── DESIGN.md                      # Design system (colors, typography, motion)
├── start-agent-server.sh          # Dev script: start agent-server in secondself
├── test-stream-viewer.sh          # Dev script: test MJPEG stream
└── .env                           # API keys (gitignored)
```

## Running the App

### Development

Terminal 1 — start agent-server in secondself's session:
```bash
bash start-agent-server.sh
```

Terminal 2 — build and run the app (auto-starts orchestrator):
```bash
cd SecondSelf && swift build && swift run
```

### Prerequisites
- secondself user created and logged in once (for GUI session)
- Screen Recording permission granted for python3 in secondself's session
- Vine Server installed and running on :5901 (optional, for TigerVNC debugging)
- API keys in `.env` (ANTHROPIC_API_KEY, TAVILY_API_KEY)

### VNC sanity check
```bash
open -a TigerVNC --args localhost:5901
```

## What's CUT for MVP

- RL training (Prime Intellect/Modal) — post-hackathon
- MongoDB Atlas — post-hackathon (JSON files for now)
- Style fingerprinting — Tier 2 onboarding, only if time
- Cookie cloning — Tier 2, only if time
- App notarization — unsigned, use `xattr -cr` bypass
- Voice input — stretch goal
- MCP integrations — post-hackathon

## Known Issues / Learnings

1. **pyautogui.screenshot() deadlocks in threads** — Cocoa APIs need the main thread. Fixed by running capture on main thread, HTTP server in background thread.
2. **JPEG doesn't support RGBA** — pyautogui returns RGBA screenshots. Must convert to RGB before JPEG encode.
3. **Xcode Python 3.9 is broken** — /usr/bin/python3 points to Xcode's Python 3.9 which can't build pyobjc. Use /opt/homebrew/bin/python3.
4. **launchctl asuser vs sudo -u** — `sudo -u secondself` runs as the user but in primary display context. `launchctl asuser 506` runs in secondself's actual GUI session.
5. **Zombie TCP sockets** — killed processes leave TIME_WAIT sockets. Use `allow_reuse_address = True` and `sudo pkill -9` before restart.
6. **URLSession MJPEG parsing** — WKWebView blocks localhost HTTP (ATS). Native URLSession with JPEG marker scanning (FFD8/FFD9) works reliably.
7. **Quartz CoreGraphics is 5x faster than pyautogui** for screenshots (~100ms vs ~500ms).

## Success Criteria

- [x] SwiftUI notch app with chat interface
- [x] SSE streaming from orchestrator to app
- [x] MJPEG live desktop feed (Quartz CoreGraphics)
- [x] Twin character with animated states
- [x] FastAPI orchestrator with job state machine
- [x] 27 passing backend tests
- [ ] Full demo loop: name → profile → twin setup → command → watch it work (2-3 min)
- [ ] Demo succeeds 8/10 cold runs with different names
- [ ] At least one MCP integration works (Google, Notion, or Slack)
- [ ] Memory layer persists across commands within a session
- [ ] No visible crashes during demo
