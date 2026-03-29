# Second Self — Layer 1 Identity Pipeline

## What this project is
A background pipeline that builds a psychological + behavioral profile of a user
(identity.md) by analyzing their Gmail data and enriching it with Tavily web search.
This profile becomes the "primer" for a digital twin agent that acts as the user.

## What you are building right now
Layer 1 of a 6-layer memory system. Your job is ONLY the identity pipeline:
- Gmail OAuth + full email fetch (all folders)
- Tavily search enrichment
- Analysis passes to extract voice, behavior, relationships, interests
- Writing the final identity.md file to ~/.secondself/identity.md

Do NOT build the twin agent, the VNC layer, the notch UI, or anything else.
Stay scoped to the identity pipeline only.

## Tech stack
- Python 3.11+
- Google Gmail API (google-auth, google-auth-oauthlib, google-api-python-client)
- Tavily Python SDK (tavily-python)
- Anthropic SDK for analysis passes (claude-sonnet-4-20250514)
- python-dotenv for env vars
- All secrets in .env, never hardcoded

## Project structure to build
```
second-self/
├── .env                          # secrets (gitignored)
├── CLAUDE.md                     # this file
├── requirements.txt
├── main.py                       # orchestrates the full pipeline
├── auth/
│   └── gmail_auth.py             # OAuth flow + token management
├── fetch/
│   ├── gmail_fetch.py            # pulls all emails, all folders
│   └── tavily_fetch.py           # web search enrichment
├── clean/
│   └── email_cleaner.py          # strips HTML, signatures, quoted chains
├── analyze/
│   ├── voice_analyzer.py         # style analysis on sent emails
│   ├── topic_extractor.py        # topic/interest extraction across all emails
│   ├── behavior_analyzer.py      # response patterns, habits
│   ├── relationship_mapper.py    # contact scoring → feeds Layer 2.5
│   └── tavily_synthesizer.py     # LLM pass on Tavily results
├── build/
│   └── identity_builder.py       # assembles identity.md from all analysis
└── output/
    └── identity.md               # final output (also written to ~/.secondself/)
```

## .env variables needed
```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8080
TAVILY_API_KEY=
ANTHROPIC_API_KEY=
USER_NAME=                # optional — auto-detected from Google sign-in
USER_EMAIL=               # optional — auto-detected from Google sign-in
```

## Gmail OAuth rules
- Scope: https://www.googleapis.com/auth/gmail.readonly (read only, all folders)
- Store token in ~/.secondself/gmail_token.json
- If token exists and is valid, skip OAuth flow — do not re-auth on every run
- If token is expired, refresh silently using the refresh token
- Only trigger the browser consent screen if no valid token exists

## Email fetch rules
- Fetch ALL folders — inbox, sent, spam excluded, trash excluded
- Use labels: fetch INBOX and SENT as separate labeled batches
- Cap: 2000 emails max total, most recent first
- For each email extract: id, threadId, labelIds, subject, from, to, cc,
  date (unix timestamp), body (plain text preferred, html fallback)
- Batch API requests — do not fetch one email at a time
- Store raw fetched emails as a local JSON cache at output/raw_emails.json
  so re-runs don't re-fetch. If cache exists and is less than 24h old, use it.
- Reconstruct threads: group emails by threadId, sort by date ascending

## Email cleaning rules
- Strip all HTML tags, convert to plain text
- Remove quoted reply chains — anything after "On [date] [name] wrote:" or
  lines starting with ">"
- Remove email signatures — detect by looking for "--" separator or
  common signature patterns (phone numbers, titles, company names in last 3 lines)
- Remove forwarded message blocks
- Remove unsubscribe links and footer boilerplate
- If cleaned body is under 10 words, discard the email entirely
- Keep the cleaned emails in memory, do not cache cleaned version

## Tavily fetch rules
- Query 1: user's full name (from USER_NAME env var)
- Query 2: user's name + their email domain (e.g. "Vin @columbia.edu")
- Query 3: user's name + "github" OR "linkedin" OR "twitter"
- Run all 3 queries, deduplicate results by URL
- Store raw Tavily results in output/tavily_raw.json

## Analysis passes — use Claude for all LLM calls
Model: claude-sonnet-4-20250514
Max tokens: 1500 per call
Temperature: 0 (deterministic — this is analysis, not generation)
Always structure prompts to return JSON — parse the response as JSON

### voice_analyzer.py
Input: sent emails only (filter by SENT label)
Analyze:
- avg_sentence_length (count words per sentence, average across corpus)
- vocabulary_markers (top 20 words/phrases used disproportionately vs general English)
- opener_patterns (how they start emails — categorize and count)
- signoff_patterns (how they end emails — categorize and count)
- emoji_frequency (total emojis / total emails, round to 2 decimal)
- question_ratio (sentences ending in "?" / total sentences)
- length_distribution (% short <50 words, % medium 50-200, % long >200)
- tone_descriptor (single word: casual / formal / terse / verbose / warm / direct)

Group sent emails by recipient email domain to detect code-switching:
- internal (same domain as user) vs external vs personal (gmail/yahoo/etc)
- Run mini voice analysis on each group
- If tone_descriptor differs between groups, capture the switching rule

Output: voice_profile.json

### topic_extractor.py
Input: all emails (cleaned)
LLM pass: "Given these email subjects and body snippets, identify the top 15 topics
that appear most frequently. For each topic return: name, frequency_count,
source (sent/inbox/both), confidence (high/medium/low based on count)"
High = 20+ mentions, medium = 5-19, low = 2-4. Discard topics with 1 mention.

Output: topics.json

### behavior_analyzer.py
Input: all emails with timestamps, grouped by thread
Analyze:
- reply_speed: median hours between receiving an email and sending a reply
- initiation_ratio: % of threads the user started vs responded to
- avg_reply_length_ratio: user's reply length / the email they're replying to
  (>1 means they write more than they receive, <1 means terse responder)
- active_hours: which hours of day have the most sent emails (bin by hour)
- active_days: which days of week
- newsletter_count: emails from no-reply/newsletter addresses in inbox (passive interests)

Output: behavior_profile.json

### relationship_mapper.py
Input: all emails
For each unique contact (by email address):
- email_count: total emails exchanged
- sent_count: emails user sent to them
- received_count: emails user received from them
- recency_score: 1.0 if last contact < 7 days, decay to 0.1 at 180+ days
- initiation_ratio: how often user starts the thread vs responds
- topics: top 3 topics from threads with this contact
- address_style: how user opens emails to them (extract from sent emails)
- closeness_score: formula → (email_count * 0.4) + (recency_score * 0.4)
  + (initiation_ratio * 0.2), normalized 0-1

Cluster by closeness_score:
- inner_circle: > 0.7
- colleagues: 0.4 - 0.7
- acquaintances: < 0.4

Take top 50 contacts only. Save as output/relationships.json
This file feeds Layer 2.5 directly — do not discard it.

### tavily_synthesizer.py
Input: tavily_raw.json
LLM pass: "Given these web search results about a person, extract:
- current_role (job title)
- current_company
- location (if findable)
- notable_projects (list, max 5)
- public_writing (blogs, papers, talks — list, max 5)
- social_profiles (dict of platform: url)
- bio_summary (2-3 sentences in third person)
- confidence (high/medium/low based on how many sources confirm this)"

Cross-reference: if current_company domain matches USER_EMAIL domain → bump confidence to high

Output: public_profile.json

## identity_builder.py — assembling the final file
Input: voice_profile.json, topics.json, behavior_profile.json,
       public_profile.json (and relationships.json exists but is separate)

Build identity.md as a markdown file. Use this exact structure:
```
# [USER_NAME]'s Identity Profile
Last updated: [ISO datetime]
Sources: Gmail ([N] emails), Tavily ([N] results)

## Who they are
[From public_profile: role, company, location, bio_summary]
Confidence: [from public_profile.confidence]

## How they write
Tone: [voice_profile.tone_descriptor]
Avg sentence length: [voice_profile.avg_sentence_length] words
Vocabulary fingerprint: [top 10 from vocabulary_markers, comma separated]
Openers: [top 2 opener patterns]
Sign-offs: [top 2 signoff patterns]
Emoji usage: [voice_profile.emoji_frequency] per email
Question tendency: [voice_profile.question_ratio, as %]
Length preference: mostly [dominant bucket from length_distribution]
Confidence: high ([N] sent email samples)

## Code-switching
[Only include this section if code-switching was detected]
- To internal colleagues: [tone]
- To external contacts: [tone]
- To personal contacts: [tone]

## What they do
[From topics where source=sent or both, top 5, with confidence]

## Interests + domain
[From topics where source=inbox or both, top 10, with confidence]
[Cross-referenced with public_profile.notable_projects]

## Behavioral patterns
Typically active: [active_hours top 2] on [active_days top 3]
Reply style: [interpret reply_speed — immediate/same-day/slow]
Initiation: [interpret initiation_ratio — mostly initiates / mostly responds]
Response length: [interpret avg_reply_length_ratio]
```

After writing, also copy the file to ~/.secondself/identity.md
If ~/.secondself/ doesn't exist, create it.
If identity.md already exists there, read it first. Only overwrite if the
new version has more email samples or the existing file is >30 days old.

## main.py — pipeline orchestration
Run steps in this order:
1. Load .env
2. Run Gmail OAuth (auth/gmail_auth.py) — get token
3. Run Tavily fetch (fetch/tavily_fetch.py) — parallel with step 4
4. Run Gmail fetch (fetch/gmail_fetch.py) — use cache if fresh
5. Run email cleaner (clean/email_cleaner.py)
6. Run all analyzers in parallel where possible:
   - voice_analyzer (needs cleaned sent emails)
   - topic_extractor (needs all cleaned emails)
   - behavior_analyzer (needs all emails with timestamps)
   - relationship_mapper (needs all emails)
   - tavily_synthesizer (needs tavily results — can run as soon as step 3 done)
7. Run identity_builder — assembles the final file
8. Print summary: how many emails processed, top 3 topics found, output path

Add a --dry-run flag that runs everything except writing the final identity.md
Add a --no-cache flag that bypasses the email cache and re-fetches
Add a --tavily-only flag for booth fast-path (skips Gmail entirely)

## Error handling rules
- If Gmail token fails: print clear error with instructions to delete
  ~/.secondself/gmail_token.json and re-run
- If Tavily returns 0 results: continue without it, mark public_profile
  sections as confidence: none
- If any analyzer fails: log the error, skip that section in identity.md,
  add a note in the file that the section is missing and why
- Never crash the whole pipeline because one analyzer failed
- If cleaned email count < 50: print a warning but continue

## Code style
- Type hints everywhere
- No print statements except in main.py — use logging module in all other files
- Log level INFO by default, DEBUG available with --verbose flag
- Each module should be independently runnable for testing
- Write one test per analyzer that runs on 5 hardcoded sample emails

## Build order for Claude Code
Build in this exact order. Complete each before starting the next.
1. Project scaffold + requirements.txt + .env template
2. auth/gmail_auth.py — OAuth flow, token storage, refresh
3. fetch/gmail_fetch.py — email fetch with caching
4. fetch/tavily_fetch.py — 3-query search
5. clean/email_cleaner.py — stripping + thread reconstruction
6. analyze/voice_analyzer.py
7. analyze/topic_extractor.py
8. analyze/behavior_analyzer.py
9. analyze/relationship_mapper.py
10. analyze/tavily_synthesizer.py
11. build/identity_builder.py
12. main.py — wire everything together with flags
13. Tests for each analyzer
