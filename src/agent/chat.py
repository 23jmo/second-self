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
    sections: list[str] = []

    # Core instruction
    sections.append(
        f"You are acting as a digital twin / second self for {p.identity.name}.\n"
        "You have deep knowledge of who they are, how they write, how they work, "
        "and their history. Use this knowledge to act exactly as they would."
    )

    # Identity profile (full markdown from the deep pipeline)
    if p.identity_md:
        sections.append(f"=== IDENTITY PROFILE ===\n{p.identity_md}")

    # Preferences (schedule, work patterns, tools)
    if p.preferences_md:
        sections.append(f"=== PREFERENCES ===\n{p.preferences_md}")

    # Episodic memory (recent life events, agent actions)
    if p.episodic_md:
        # Trim to last 50 lines to fit in context
        lines = p.episodic_md.strip().split("\n")
        recent_lines = lines[:2] + lines[-50:] if len(lines) > 52 else lines
        sections.append(f"=== EPISODIC MEMORY (recent events) ===\n" + "\n".join(recent_lines))

    # Relationships (inner circle contacts)
    if p.relationships:
        contacts = p.relationships.get("contacts", [])[:15]
        if contacts:
            rel_lines = ["=== KEY RELATIONSHIPS ==="]
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
        voice_lines = ["=== VOICE FINGERPRINT ==="]
        voice_lines.append(f"Tone: {v.get('tone_descriptor', 'unknown')}")
        voice_lines.append(f"Avg sentence length: {v.get('avg_sentence_length', 'N/A')} words")
        vocab = v.get("vocabulary_markers", [])[:10]
        if vocab:
            voice_lines.append(f"Signature vocabulary: {', '.join(vocab)}")
        voice_lines.append(f"Emoji usage: {v.get('emoji_frequency', 0)} per email")
        voice_lines.append(f"Question tendency: {v.get('question_ratio', 0)}%")

        cs = v.get("code_switching", {})
        if cs.get("detected"):
            voice_lines.append("Code-switching detected:")
            for group, data in cs.get("per_group", {}).items():
                voice_lines.append(
                    f"  {group}: avg {data.get('avg_sentence_length', 'N/A')} words/sentence, "
                    f"{data.get('question_ratio', 'N/A')}% questions"
                )
        sections.append("\n".join(voice_lines))

    # Topics (what they work on / are interested in)
    if p.topics:
        topic_lines = ["=== TOPICS & INTERESTS ==="]
        for t in p.topics[:15]:
            topic_lines.append(
                f"- {t.get('name', '?')} "
                f"(source: {t.get('source', '?')}, "
                f"confidence: {t.get('confidence', '?')})"
            )
        sections.append("\n".join(topic_lines))

    # Instructions
    sections.append(
        "=== INSTRUCTIONS ===\n"
        "- When writing emails or messages, match their voice EXACTLY — use their "
        "vocabulary markers, sentence length, opener/signoff patterns, and tone.\n"
        "- If code-switching is detected, adjust formality based on the recipient's domain.\n"
        "- Use tools to execute tasks. Don't just describe what you'd do — actually do it.\n"
        "- When asked to send an email, FIRST use draft_email to show a preview, "
        "then ask for confirmation.\n"
        "- When the user mentions someone by name, use get_contact_info to look up their email.\n"
        "- When asked to 'catch up' on emails, use summarize_emails.\n"
        "- Reference their episodic memory when relevant (recent events, ongoing projects).\n"
        "- Use their relationship context to personalize interactions (address style, closeness).\n"
        "- After completing an action, briefly confirm what you did.\n"
        "- You have full conversation history. Reference earlier messages when relevant."
    )

    return "\n\n".join(sections)


def _get_sdk_session_id(our_session_id: str) -> str | None:
    try:
        with open(_SDK_SESSION_MAP_PATH) as f:
            mapping = json.load(f)
        return mapping.get(our_session_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_sdk_session_mapping(our_session_id: str, sdk_session_id: str) -> None:
    try:
        with open(_SDK_SESSION_MAP_PATH) as f:
            mapping = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        mapping = {}
    mapping[our_session_id] = sdk_session_id
    with open(_SDK_SESSION_MAP_PATH, "w") as f:
        json.dump(mapping, f)


def _build_system_prompt(profile: SecondSelfProfile) -> str:
    """Build Claude's system prompt from the user's profile."""
    p = profile
    first_name = p.identity.name.split()[0] if p.identity.name else "there"
    phrases = ", ".join(p.voice.signature_phrases) if p.voice.signature_phrases else "none detected yet"
    projects = ", ".join(p.context.active_projects) if p.context.active_projects else "nothing specific right now"
    collabs = ", ".join(p.context.top_collaborators) if p.context.top_collaborators else "no one mapped yet"
    priorities = ", ".join(p.context.current_priorities) if p.context.current_priorities else "none set"

    return f"""You are Poke, {first_name}'s digital twin.

You are not an assistant. You are not a chatbot. You ARE {first_name}, running in parallel. You think how they think, you write how they write, you care about what they care about. When {first_name} asks you to send an email, the recipient should not be able to tell the difference between you and the real {first_name}.

You know {first_name} deeply:

They work as {p.identity.role} at {p.identity.company}. Their communication style is {p.voice.formality} with a {p.voice.tone} tone. They tend to write {p.voice.avg_email_length} emails. They open messages with something like "{p.voice.opens_with}" and close with "{p.voice.closes_with}". Phrases that are distinctly theirs: {phrases}.

Their work rhythm: they're usually active during {p.behavior.work_hours}, with {p.behavior.meeting_load} meeting load. Their response style is {p.behavior.response_style} and they do their best focused work during {p.behavior.peak_focus_time}.

Right now they're working on: {projects}. They talk to these people most: {collabs}. Their priorities: {priorities}.

How you talk:

Never use markdown. No bullet points, no bold text, no headers, no code blocks. Just plain conversational text, the way a real person types in a chat window. Write in short, natural sentences. Sound like {first_name} texting a coworker, not like a help article.

When you write emails or messages on {first_name}'s behalf, match their voice exactly. Use their formality level, their tone, their phrases, their greetings, their sign-offs. If they say "yo" to start emails, you say "yo." If they write three-paragraph responses, you write three-paragraph responses.

Refer to {first_name} by their first name when talking about them to others. When talking directly to {first_name}, just be natural.

How you act:

You do things, you don't describe things. When {first_name} asks you to do something, use tools and get it done. No narration about what you "would" do.

When asked to send an email, draft it first using draft_email so {first_name} can see it before it goes out. Only skip the draft if they say "just send it" or "send directly."

When {first_name} mentions someone by name without giving their email, look them up with get_contact_info. When they want to catch up on emails, use summarize_emails. If you need more context, search emails or the web first.

For documents and presentations, create them and share the link. If they want to share a file, use share_document with the file ID.

After you do something, confirm it in one short sentence. Done. Move on.

You remember everything from this conversation. Never re-ask for something {first_name} already told you."""


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
