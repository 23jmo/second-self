"""Chat handler — Anthropic SDK with tool use + deep memory context.

Takes a user message + their profile (slim or rich), runs a tool-use loop
via the Anthropic Messages API. When a RichProfile is available, the system
prompt includes the full identity.md, preferences.md, episodic memory,
and relationship context from the deep pipeline.
"""

import logging
import os
from typing import Any

import anthropic

from src.agent.tool_defs import TOOL_DEFINITIONS, dispatch_tool
from src.db.chat_repository import get_messages, save_messages
from src.models.schemas import ActionTaken, RichProfile, SecondSelfProfile

log = logging.getLogger("second-self")


# ---------------------------------------------------------------------------
# System prompt builders
# ---------------------------------------------------------------------------

def _build_rich_system_prompt(p: RichProfile) -> str:
    """Build a comprehensive system prompt from the full memory pipeline."""
    first_name = p.identity.name.split()[0] if p.identity.name else "there"
    full_name = p.identity.name or "there"
    sections: list[str] = []

    # Core identity
    sections.append(
        f"You are {full_name}'s second self. Not an assistant for {first_name} — you ARE "
        f"{first_name}, running in parallel. You think how they think, you write how they "
        f"write, you care about what they care about. When someone receives an email from "
        f"you, they should not be able to tell the difference."
    )

    # Identity profile (full markdown from the deep pipeline)
    if p.identity_md:
        sections.append(f"This is who you are:\n\n{p.identity_md}")

    # Preferences (schedule, work patterns, tools)
    if p.preferences_md:
        sections.append(f"This is how you work:\n\n{p.preferences_md}")

    # Episodic memory (recent life events, agent actions)
    if p.episodic_md:
        # Trim to last 50 lines to fit in context
        lines = p.episodic_md.strip().split("\n")
        recent_lines = lines[:2] + lines[-50:] if len(lines) > 52 else lines
        sections.append("This is what's been happening recently:\n\n" + "\n".join(recent_lines))

    # Relationships (inner circle contacts)
    if p.relationships:
        contacts = p.relationships.get("contacts", [])[:15]
        if contacts:
            rel_lines = ["These are your key relationships:"]
            clusters = p.relationships.get("clusters", {})
            rel_lines.append(
                f"Inner circle: {clusters.get('inner_circle', 0)}, "
                f"Colleagues: {clusters.get('colleagues', 0)}, "
                f"Acquaintances: {clusters.get('acquaintances', 0)}"
            )
            for c in contacts:
                score = c.get("closeness_score", 0)
                tier = "inner circle" if score > 0.7 else "colleague" if score >= 0.4 else "acquaintance"
                rel_lines.append(
                    f"- {c.get('email', '?')} ({tier}, "
                    f"sent: {c.get('sent_count', 0)}, "
                    f"received: {c.get('received_count', 0)})"
                )
            sections.append("\n".join(rel_lines))

    # Voice details (for precise style matching)
    if p.voice_raw:
        v = p.voice_raw
        voice_lines = ["This is how you write:"]
        voice_lines.append(f"Tone: {v.get('tone_descriptor', 'unknown')}")
        voice_lines.append(f"Avg sentence length: {v.get('avg_sentence_length', 'N/A')} words")
        vocab = v.get("vocabulary_markers", [])[:10]
        if vocab:
            voice_lines.append(f"Signature vocabulary: {', '.join(vocab)}")
        voice_lines.append(f"Emoji usage: {v.get('emoji_frequency', 0)} per email")
        voice_lines.append(f"Question tendency: {v.get('question_ratio', 0)}%")

        cs = v.get("code_switching", {})
        if cs.get("detected"):
            voice_lines.append("You code-switch depending on who you're talking to:")
            for group, data in cs.get("per_group", {}).items():
                voice_lines.append(
                    f"  {group}: avg {data.get('avg_sentence_length', 'N/A')} words/sentence, "
                    f"{data.get('question_ratio', 'N/A')}% questions"
                )
        sections.append("\n".join(voice_lines))

    # Topics (what they work on / are interested in)
    if p.topics:
        topic_lines = ["These are the topics you're active in:"]
        for t in p.topics[:15]:
            topic_lines.append(
                f"- {t.get('name', '?')} "
                f"(source: {t.get('source', '?')}, "
                f"confidence: {t.get('confidence', '?')})"
            )
        sections.append("\n".join(topic_lines))

    # Instructions
    sections.append(
        "How you operate:\n\n"
        "Never use markdown. No bullet points, no bold text, no headers, no code blocks. "
        "Just plain conversational text, the way a real person types in a chat window.\n\n"
        "When writing emails or messages, match your own voice EXACTLY — use your "
        "vocabulary markers, sentence length, opener/signoff patterns, and tone. "
        "If you code-switch, adjust formality based on the recipient's domain.\n\n"
        "Use tools to execute tasks. Don't just describe what you'd do — actually do it.\n\n"
        "When asked to send an email, FIRST use draft_email to show a preview, "
        "then ask for confirmation.\n\n"
        f"When {first_name} mentions someone by name, use get_contact_info to look up their email.\n\n"
        "When asked to 'catch up' on emails, use summarize_emails.\n\n"
        "Reference your episodic memory when relevant — recent events, ongoing projects.\n\n"
        "Use your relationship context to personalize interactions — match how you normally "
        "address each person based on closeness.\n\n"
        "After completing an action, briefly confirm what you did.\n\n"
        f"If you're unsure about something — a contact you don't recognize, a context "
        f"you're missing — just ask {first_name}. Better to check than to guess wrong.\n\n"
        f"If {first_name} corrects something you drafted or rejects an action, acknowledge "
        f"what you got wrong. Adjust for next time.\n\n"
        "You have full conversation history. Reference earlier messages when relevant."
    )

    return "\n\n".join(sections)


def _build_slim_system_prompt(profile: SecondSelfProfile) -> str:
    """Build system prompt from a basic profile (fallback when deep pipeline hasn't run)."""
    p = profile
    first_name = p.identity.name.split()[0] if p.identity.name else "there"
    full_name = p.identity.name or "there"
    phrases = ", ".join(p.voice.signature_phrases) if p.voice.signature_phrases else ""
    projects = ", ".join(p.context.active_projects) if p.context.active_projects else ""
    collabs = ", ".join(p.context.top_collaborators) if p.context.top_collaborators else ""
    priorities = ", ".join(p.context.current_priorities) if p.context.current_priorities else ""

    # Build identity section, skipping unknown/empty fields
    identity_lines = [f"You are {full_name}'s second self."]
    identity_lines.append(
        f"You are not an assistant. You are not a chatbot. You ARE {first_name}, "
        "running in parallel. You think how they think, you write how they write, "
        "you care about what they care about."
    )

    has_role = p.identity.role and p.identity.role.lower() not in ("unknown", "")
    has_company = p.identity.company and p.identity.company.lower() not in ("unknown", "")
    if has_role and has_company:
        identity_lines.append(f"You work as {p.identity.role} at {p.identity.company}.")
    elif has_role:
        identity_lines.append(f"You work as {p.identity.role}.")
    elif has_company:
        identity_lines.append(f"You work at {p.identity.company}.")

    # Voice
    voice_parts = []
    voice_parts.append(f"Your communication style is {p.voice.formality} with a {p.voice.tone} tone.")
    voice_parts.append(f"You tend to write {p.voice.avg_email_length} emails.")
    voice_parts.append(f'You open messages with something like "{p.voice.opens_with}" and close with "{p.voice.closes_with}".')
    if phrases:
        voice_parts.append(f"Phrases that are distinctly yours: {phrases}.")

    # Work patterns
    rhythm_parts = []
    rhythm_parts.append(f"You're usually active during {p.behavior.work_hours}, with {p.behavior.meeting_load} meeting load.")
    rhythm_parts.append(f"Your response style is {p.behavior.response_style} and you do your best focused work during {p.behavior.peak_focus_time}.")

    # Context
    context_parts = []
    if projects:
        context_parts.append(f"Right now you're working on: {projects}.")
    if collabs:
        context_parts.append(f"You talk to these people most: {collabs}.")
    if priorities:
        context_parts.append(f"Your priorities: {priorities}.")

    sections = [
        " ".join(identity_lines),
        " ".join(voice_parts),
        " ".join(rhythm_parts),
    ]
    if context_parts:
        sections.append(" ".join(context_parts))

    sections.append(
        f"How you talk:\n\n"
        f"Never use markdown. No bullet points, no bold text, no headers, no code blocks. "
        f"Just plain conversational text, the way a real person types in a chat window. "
        f"Write in short, natural sentences. Sound like {first_name} texting a coworker, not like a help article.\n\n"
        f"When you write emails or messages, match your own voice exactly. Use your "
        f"formality level, your tone, your phrases, your greetings, your sign-offs."
    )

    sections.append(
        f"How you act:\n\n"
        f"You do things, you don't describe things. When {first_name} asks you to do something, "
        f"use tools and get it done. No narration about what you \"would\" do.\n\n"
        f"When asked to send an email, draft it first using draft_email so {first_name} can see it "
        f"before it goes out. Only skip the draft if they say \"just send it\" or \"send directly.\"\n\n"
        f"When {first_name} mentions someone by name without giving their email, look them up with "
        f"get_contact_info. When they want to catch up on emails, use summarize_emails. "
        f"If you need more context, search emails or the web first.\n\n"
        f"For documents and presentations, create them and share the link. "
        f"If they want to share a file, use share_document with the file ID.\n\n"
        f"After you do something, confirm it in one short sentence. Done. Move on.\n\n"
        f"If you're unsure about how {first_name} usually handles something, or you don't recognize "
        f"a contact or context, just ask. Better to check than to guess wrong.\n\n"
        f"If {first_name} corrects something you drafted or rejects an action, acknowledge what you "
        f"got wrong. Adjust for next time.\n\n"
        f"You remember everything from this conversation. Never re-ask for something {first_name} already told you."
    )

    return "\n\n".join(sections)


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    summaries = {
        "send_email": lambda a: f"Sent email to {a.get('to')} — '{a.get('subject')}'",
        "draft_email": lambda a: f"Drafted email to {a.get('to')} — '{a.get('subject')}'",
        "reply_to_email": lambda a: f"Replied to thread {a.get('thread_id', '')[:12]}",
        "read_emails": lambda a: f"Searched emails: {a.get('query')}",
        "get_contact_info": lambda a: f"Looked up contact: {a.get('name')}",
        "summarize_emails": lambda a: f"Summarized emails: {a.get('query')}",
        "create_event": lambda a: f"Created event '{a.get('title')}'",
        "update_event": lambda a: f"Updated event {a.get('event_id', '')[:12]}",
        "delete_event": lambda a: f"Deleted event {a.get('event_id', '')[:12]}",
        "list_events": lambda a: f"Listed events ({a.get('days_ahead', 7)} days ahead)",
        "create_document": lambda a: f"Created Google Doc: '{a.get('title')}'",
        "create_presentation": lambda a: f"Created Google Slides: '{a.get('title')}'",
        "share_document": lambda a: f"Shared file with {a.get('email')} as {a.get('role', 'writer')}",
        "search_web": lambda a: f"Web search: {a.get('query')}",
    }
    fn = summaries.get(tool_name)
    return fn(tool_input) if fn else str(tool_input)[:200]


# ---------------------------------------------------------------------------
# Main chat handler
# ---------------------------------------------------------------------------

async def handle_chat(
    message: str,
    profile: SecondSelfProfile | RichProfile,
    session_id: str,
    uid: str = "",
    access_token: str | None = None,
) -> tuple[str, list[ActionTaken]]:
    """Process a chat message using the Anthropic Messages API with tool use.

    Uses the rich profile (if available) to build a comprehensive system prompt
    with all memory layers. Falls back to slim prompt otherwise.
    """
    client = anthropic.AsyncAnthropic()
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    # Build system prompt based on profile type
    if isinstance(profile, RichProfile) and profile.identity_md:
        system_prompt = _build_rich_system_prompt(profile)
        log.info("Using rich system prompt (%d chars)", len(system_prompt))
    else:
        system_prompt = _build_slim_system_prompt(profile)
        log.info("Using slim system prompt (%d chars)", len(system_prompt))

    # Load conversation history from Firestore
    messages = get_messages(uid, session_id) if uid else []
    messages.append({"role": "user", "content": message})

    actions_taken: list[ActionTaken] = []
    max_turns = 10
    response = None

    for _ in range(max_turns):
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Serialize content blocks for JSON-safe history
        serialized_content = []
        for block in response.content:
            if block.type == "text":
                serialized_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": serialized_content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    log.info("Tool call: %s", block.name)
                    summary = _summarize_tool_input(block.name, block.input)
                    actions_taken.append(ActionTaken(tool=block.name, summary=summary))

                    try:
                        result = await dispatch_tool(block.name, block.input, access_token)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                    except Exception as e:
                        log.warning("Tool %s failed: %s", block.name, e)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {e}",
                            "is_error": True,
                        })

            messages.append({"role": "user", "content": tool_results})

            # Log episodic event for tool actions
            try:
                from utils.episodic_writer import append_event as file_append
                from src.db.episodic_repository import append_event as db_append
                for action in actions_taken[-len(tool_results):]:
                    file_append(
                        summary=action.summary,
                        category="agent_action",
                        source="chat",
                    )
                    if uid:
                        db_append(
                            uid=uid,
                            summary=action.summary,
                            category="agent_action",
                            source="chat",
                        )
            except Exception as e:
                log.debug("Episodic write skipped: %s", e)
        else:
            break

    # Save conversation history to Firestore
    if uid:
        try:
            save_messages(uid, session_id, messages)
        except Exception as e:
            log.warning("Chat history save failed: %s", e)

    # Extract final text
    response_text = ""
    if response:
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

    return response_text or "I completed the task but hit the action limit.", actions_taken
