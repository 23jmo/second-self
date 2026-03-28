# Second Self — Integrate agent-browser for Browser Automation

## Context

Phase 1 plumbing is proven: VNC works (Vine Server :5901 + TigerVNC), Agent Server runs in secondself's GUI session (:8421), `open` commands work for apps/URLs, PyAutoGUI works for mouse/keyboard.

**Problem:** PyAutoGUI screenshot→LLM→click is slow (~6MB screenshots, multi-second round trips) and fragile for browser tasks. Most demo tasks are web browsing.

**Solution:** Replace PyAutoGUI browser control with **agent-browser** (Vercel Labs). Keep PyAutoGUI only for desktop-level tasks.

## What is agent-browser?

- Free, open source Rust CLI from Vercel Labs
- Uses Chromium via Playwright, ref-based element selection (`@e1`, `@e2`)
- CLI commands: `goto`, `click @e3`, `fill @e5 "search query"`, `snapshot`, `screenshot`
- Works with any LLM (designed for Claude Code, Cursor, etc.)
- Shows visible Chrome window (appears in VNC)
- Install: `npm install -g agent-browser`

## Files to modify

1. **`agent-server/server.py`** — Add browser endpoints that shell out to agent-browser CLI
2. **`orchestrator/server.py`** — Update tool definitions to include browser tools, update agent loop
3. **`setup/provision.sh`** — Add agent-browser install step
4. **`setup/test-agent.sh`** — Update test to use browser commands

## Architecture

```
PRIMARY SESSION                         SECOND SELF SESSION
─────────────────                       ─────────────────────

┌─────────────────────┐                 ┌──────────────────────────┐
│  Menubar App        │                 │  Agent Server (Python)   │
│  (Swift/SwiftUI)    │                 │  port 8421               │
│                     │                 │                          │
│  ┌───────────────┐  │   HTTP :8420    │  BROWSER (agent-browser) │
│  │ Input Pill    │──┼──────────────►  │  /browser/goto           │
│  └───────────────┘  │                 │  /browser/click          │
│  ┌───────────────┐  │   VNC :5901    │  /browser/fill           │
│  │ TigerVNC      │◄─┼──────────────  │  /browser/snapshot       │
│  └───────────────┘  │                 │  /browser/screenshot     │
└────────┬────────────┘                 │  /browser/text           │
         │                              │                          │
         ▼                              │  DESKTOP (PyAutoGUI)     │
┌─────────────────────┐                 │  /tool/open_app          │
│  Orchestrator       │                 │  /tool/click (pixels)    │
│  (Python, port 8420)│                 │  /tool/type              │
│                     │  Dedalus API    │  /tool/hotkey            │
│  Tavily Profiler    │────────────►    │                          │
│  Command Router     │  LLM returns   │  Chrome visible in VNC   │
│  Tool Executor      │◄────────────   │  agent-browser daemon    │
└─────────────────────┘  tool calls    └──────────────────────────┘
```

**Key change:** The Orchestrator sends browser tasks as natural language to the LLM. The LLM returns agent-browser CLI commands (goto, click, fill) instead of PyAutoGUI pixel coordinates. The Agent Server executes them via subprocess. Chrome opens visibly in secondself's session (visible in VNC).

## Implementation plan

### Step 1: Install agent-browser on secondself
```bash
# From primary account
sudo -H -u secondself npm install -g agent-browser
```

### Step 2: Add browser endpoints to Agent Server
New endpoints that shell out to `agent-browser` CLI:

```
POST /browser/goto     { url }         → agent-browser goto <url>
POST /browser/click    { ref }         → agent-browser click @<ref>
POST /browser/fill     { ref, text }   → agent-browser fill @<ref> "<text>"
POST /browser/snapshot {}              → agent-browser snapshot -i
POST /browser/screenshot {}            → agent-browser screenshot
POST /browser/text     {}              → agent-browser text
POST /browser/press    { key }         → agent-browser press <key>
POST /browser/task     { task }        → Full agent loop: LLM plans steps,
                                         executes browser commands, returns result
```

The `/browser/task` endpoint is the high-level one: give it a natural language task, it runs a loop of snapshot→LLM→action until done.

### Step 3: Update Orchestrator tool definitions
Replace PyAutoGUI browser tools with agent-browser tools in the Dedalus function calling schema. The LLM gets:
- `browser_goto(url)` — navigate to URL
- `browser_click(ref)` — click element by ref
- `browser_fill(ref, text)` — fill input by ref
- `browser_snapshot()` — get page structure with refs
- `browser_task(task)` — high-level: "search Google for X"
- `open_app(name)` — desktop: open an app (PyAutoGUI)
- `type_text(text)` — desktop: type on keyboard (PyAutoGUI)
- `hotkey(keys)` — desktop: keyboard shortcut (PyAutoGUI)

### Step 4: Update test script
```bash
# Test: open Google, search for "Johnathan Mo"
curl -X POST http://localhost:8421/browser/goto \
  -H "Content-Type: application/json" \
  -d '{"url":"https://google.com"}'

curl -X POST http://localhost:8421/browser/snapshot \
  -H "Content-Type: application/json" -d '{}'
# Returns element refs like @e1=search box

curl -X POST http://localhost:8421/browser/fill \
  -H "Content-Type: application/json" \
  -d '{"ref":"e1", "text":"Johnathan Mo"}'

curl -X POST http://localhost:8421/browser/press \
  -H "Content-Type: application/json" \
  -d '{"key":"Enter"}'
```

## What stays the same
- VNC setup (Vine Server :5901, TigerVNC)
- Agent Server HTTP framework (port 8421)
- Orchestrator structure (port 8420)
- Dedalus as LLM brain
- Tavily for profiling
- PyAutoGUI for desktop-only tasks (open_app, hotkey, desktop click/type)

## What changes
- Browser tasks use agent-browser CLI instead of PyAutoGUI pixel-clicking
- No more slow screenshots for browser navigation
- Element selection by ref (`@e1`) instead of pixel coordinates
- Chrome profile support built-in (for cookie sharing later)

## Verification
1. `agent-browser goto https://google.com` opens Chrome visibly in VNC
2. `agent-browser snapshot -i` returns element refs
3. `curl POST /browser/task '{"task":"search Google for Johnathan Mo"}'` completes successfully
4. Watch in TigerVNC: Chrome navigates, types, searches without PyAutoGUI
