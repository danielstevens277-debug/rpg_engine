#!/usr/bin/env python3
"""
RPG Engine - Core Game Logic
==============================
Handles game state persistence, LLM integration, character creation,
and the main game loop. All mechanics are handled invisibly by the LLM
acting as a system-agnostic Dungeon Master.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from threading import Event, Thread, Lock

# ---------------------------------------------------------------------------
# Terminal helpers (no external deps required)
# ---------------------------------------------------------------------------

# ANSI color codes
_C = {
    "dim":      "\033[2m",
    "reset":    "\033[0m",
    "white":    "\033[37m",
    "cyan":     "\033[36m",
    "green":    "\033[32m",
    "yellow":   "\033[33m",
    "red":      "\033[31m",
    "blue":     "\033[34m",
    "magenta":  "\033[35m",
    "bold":     "\033[1m",
    "underline":"\033[4m",
}

def _c(text, *colors):
    """Apply color codes to text."""
    seq = "".join(_C.get(c, "") for c in colors)
    return f"{seq}{text}{_C['reset']}"


def _print_sep(char="=", color="cyan", width=62):
    print(_c(char * width, color))


_stdout_lock = Lock()


def _show_thinking(duration: float = 1.5):
    """
    Show a thematic "Dungeon Master is thinking" indicator on a single line.
    The dots animate in-place (using carriage return) as if the Oracle is pondering.
    The line is automatically cleared when the animation stops so it does not
    interfere with subsequent thinking or output blocks.

    Parameters:
        duration: Seconds to show the animation. Pass None to run
                  indefinitely until stop_thinking() is called.

    Returns:
        A tuple of (end_event, thread). Call end_event.set() and
        thread.join() to stop the animation, or pass duration=None
        and stop manually after the work is done.
    """
    dots = [".", "..", "..."]
    end_event = Event()
    line = _c(f"  The Oracle ponders  {dots[0]}", "dim")

    def _animate():
        nonlocal line
        elapsed = 0.0
        dot_idx = 0
        while not end_event.is_set():
            if duration is not None:
                time.sleep(0.4)
                elapsed += 0.4
                if elapsed >= duration:
                    break
            else:
                time.sleep(0.4)
            with _stdout_lock:
                sys.stdout.write(f"\r{line}")
                sys.stdout.flush()
            dot_idx = (dot_idx + 1) % len(dots)
            line = _c(f"  The Oracle ponders  {dots[dot_idx]}", "dim")

    thread = Thread(target=_animate, daemon=True)
    thread.start()

    # Wait for the full duration if finite
    if duration is not None:
        time.sleep(duration)
        end_event.set()
        thread.join(timeout=0.5)

    return end_event, thread


def _clear_thinking_line():
    """Clear the single-line thinking animation so it doesn't interfere with blocks."""
    with _stdout_lock:
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()


def _stop_thinking(end_event, thread):
    """Stop a thinking animation started with _show_thinking(duration=None)."""
    end_event.set()
    thread.join(timeout=0.5)
    _clear_thinking_line()


# ---------------------------------------------------------------------------
# Output blocks
# ---------------------------------------------------------------------------

_BLOCK_SEP = "─" * 58


def _print_block(title: str, text: str, *colors):
    """
    Print a titled, bordered block of text.

    Parameters:
        title:  Block title (e.g. "Thinking" or "Output")
        text:   The block content
        colors: Color codes to apply to the title
    """
    with _stdout_lock:
        print()
        print(_c(_BLOCK_SEP, *colors))
        print(_c(f"  {title}", *colors))
        print(_c(_BLOCK_SEP, *colors))
        print(_c(text, *colors))
        print(_c(_BLOCK_SEP, *colors))


# ---------------------------------------------------------------------------
# LLM integration
# ---------------------------------------------------------------------------

def _get_api_config():
    """Read API configuration from environment variables."""
    provider = os.environ.get("RPG_LLM_PROVIDER", "openai")
    provider = provider.lower()
    api_key = os.environ.get("RPG_API_KEY", "") or os.environ.get(f"RPG_{provider.upper()}_API_KEY", "")
    base_url = os.environ.get("RPG_BASE_URL", "")
    model = os.environ.get("RPG_MODEL", "")

    # Try common env var names for fallback
    # Provider-specific fallbacks (must run before generic OpenAI fallbacks)
    if provider == "anthropic" and not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if provider == "anthropic" and not model:
        model = os.environ.get("RPG_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # Generic OpenAI fallbacks
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not base_url:
        base_url = os.environ.get("OPENAI_BASE_URL", "") or os.environ.get("RPG_OPENAI_BASE_URL", "")
    if not model:
        model = os.environ.get("RPG_OPENAI_MODEL", "gpt-4o-mini")

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def _get_max_tokens(client, model_name):
    """Query the API for the model's context length and return a safe max_tokens budget."""
    try:
        # Try to fetch model metadata
        model_info = client.models.retrieve(model=model_name)
        ctx = None
        for attr in ("context_length", "max_input_tokens", "max_context_tokens"):
            ctx = getattr(model_info, attr, None)
            if ctx:
                break
        if ctx and isinstance(ctx, (int, float)) and ctx > 0:
            # Leave 4k headroom for system prompt + response
            return int(min(ctx * 0.95, ctx - 4096))
    except Exception:
        pass
    # Fallback: use the caller's default
    return None


def _call_llm(messages, temperature=0.85, max_tokens=16384, stream=True,
              thinking_end=None, thinking_thread=None):
    """
    Call the LLM API. Supports OpenAI-compatible endpoints and Anthropic.
    Streams tokens to stdout in real-time when stream=True.
    Returns a tuple of (response_text, reasoning_content, thinking_end, thinking_thread)
    where reasoning_content may be None if the model did not produce any.
    """
    config = _get_api_config()

    if config["provider"] == "anthropic":
        return _call_anthropic(config, messages, temperature, max_tokens, stream=stream,
                               thinking_end=thinking_end, thinking_thread=thinking_thread)

    # Default: OpenAI-compatible API
    try:
        import openai
    except ImportError:
        print("\n  The 'openai' Python package is required.")
        print("     Install it with: pip install openai\n")
        sys.exit(1)

    try:
        kwargs = {}
        if config["api_key"]:
            kwargs["api_key"] = config["api_key"]
        if config["base_url"]:
            kwargs["base_url"] = config["base_url"]

        client = openai.OpenAI(**kwargs)

        # Query the endpoint for the model's actual context length
        effective_max = _get_max_tokens(client, config["model"])
        if effective_max is not None:
            max_tokens = effective_max

        kwargs = {
            "model": config["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if stream:
            return _stream_openai(client, kwargs, thinking_end, thinking_thread)
        else:
            return _nonstream_openai(client, kwargs, thinking_end, thinking_thread)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        _stop_thinking(thinking_end, thinking_thread)
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg:
            return (
                "  The connection to the Oracle has been lost.\n"
                "     Please check your internet connection and try again.",
                None,
                thinking_end,
                thinking_thread,
            )
        elif "rate" in error_msg or "limit" in error_msg:
            return (
                "  The Oracle is speaking slowly... Please wait a moment.",
                None,
                thinking_end,
                thinking_thread,
            )
        else:
            return (
                f"  The Oracle stumbles: {str(e)[:200]}\n"
                "     Please try again.",
                None,
                thinking_end,
                thinking_thread,
            )


def _nonstream_openai(client, kwargs, thinking_end, thinking_thread):
    """Non-streaming OpenAI call. Returns (content, reasoning, thinking_end, thinking_thread)."""
    response = client.chat.completions.create(**kwargs)
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        reasoning = getattr(message, "reasoning_content", None)
        if content is not None:
            _stop_thinking(thinking_end, thinking_thread)
            if reasoning:
                _print_block("  Thinking", reasoning.strip(), "dim")
            _print_block("  Output", content.strip())
            return content, reasoning, thinking_end, thinking_thread
    return "  The Oracle is silent. Please try again.", None, thinking_end, thinking_thread


def _stream_openai(client, kwargs, thinking_end, thinking_thread):
    """
    Streaming OpenAI call. Prints tokens to stdout as they arrive.
    Thinking content appears in a separate dim block; output in its own block.
    Returns (full_content, full_reasoning, thinking_end, thinking_thread).
    """
    stream = client.chat.completions.create(**kwargs)
    full_content = ""
    full_reasoning = ""

    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if not delta:
                continue

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                full_reasoning += reasoning

            content = getattr(delta, "content", None)
            if content:
                full_content += content
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass

    # Stop thinking animation before printing blocks
    _stop_thinking(thinking_end, thinking_thread)

    # Print blocks after streaming completes
    if full_reasoning:
        _print_block("  Thinking", full_reasoning.strip(), "dim")
    if full_content:
        _print_block("  Output", full_content.strip())

    return full_content, full_reasoning if full_reasoning else None, thinking_end, thinking_thread


def _get_anthropic_max_tokens(api_key, model_name, base_url=None):
    """Query Anthropic API for the model's context length."""
    try:
        import httpx
        url = (base_url or "https://api.anthropic.com") + f"/v1/messages/models/{model_name}"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for attr in ("context_window", "context_length", "max_input_tokens"):
                ctx = data.get(attr)
                if ctx and isinstance(ctx, (int, float)) and ctx > 0:
                    return int(min(ctx * 0.95, ctx - 4096))
    except Exception:
        pass
    return None


def _call_anthropic(config, messages, temperature, max_tokens, stream=True,
                    thinking_end=None, thinking_thread=None):
    """
    Call Anthropic's Claude API.
    Streams tokens to stdout in real-time when stream=True.
    Returns a tuple of (response_text, thinking_content, thinking_end, thinking_thread).
    """
    try:
        import anthropic
    except ImportError:
        print("\n  The 'anthropic' Python package is required for Claude.\n")
        sys.exit(1)

    kwargs = {}
    if config["api_key"]:
        kwargs["api_key"] = config["api_key"]

    # Convert OpenAI-style messages to Anthropic format
    # Anthropic requires alternating roles starting with user. Strip leading non-user
    # messages and merge consecutive messages with the same role.
    system_parts = []
    user_messages = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            system_parts.append(msg["content"])
        else:
            user_messages.append({"role": role, "content": msg.get("content", "")})
    system_msg = "\n\n".join(system_parts) if system_parts else None

    # Merge consecutive messages with the same role, then strip leading non-user messages
    merged = []
    for m in user_messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] = merged[-1]["content"] + "\n\n" + m["content"]
        else:
            merged.append(m)

    # Strip leading non-user messages so first message is always user
    while merged and merged[0]["role"] != "user":
        merged.pop(0)

    # Fallback: ensure at least one user message
    if not merged:
        merged = [{"role": "user", "content": "..."}]

    # base_url support was added in anthropic SDK v0.35.0
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]

    try:
        try:
            client = anthropic.Anthropic(**kwargs)
        except TypeError:
            # Older SDK version doesn't support base_url; retry without it
            kwargs.pop("base_url", None)
            client = anthropic.Anthropic(**kwargs)

        # Query the endpoint for the model's actual context length
        effective_max = _get_anthropic_max_tokens(
            config["api_key"], config["model"] or "claude-sonnet-4-20250514",
            config.get("base_url")
        )
        if effective_max is not None:
            max_tokens = effective_max

        # Enable thinking with a budget proportional to the context window
        thinking_budget = max(8192, min(max_tokens // 2, 131072))
        model_name = config["model"] or "claude-sonnet-4-20250514"

        if stream:
            return _stream_anthropic(client, system_msg, merged, temperature,
                                     max_tokens, thinking_budget, model_name,
                                     thinking_end, thinking_thread)
        else:
            return _nonstream_anthropic(client, system_msg, merged, temperature,
                                        max_tokens, thinking_budget, model_name,
                                        thinking_end, thinking_thread)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        _stop_thinking(thinking_end, thinking_thread)
        return f"  The Oracle stumbles: {str(e)[:200]}", None, thinking_end, thinking_thread


def _nonstream_anthropic(client, system_msg, merged, temperature, max_tokens,
                         thinking_budget, model_name, thinking_end, thinking_thread):
    """Non-streaming Anthropic call. Returns (text, thinking, thinking_end, thinking_thread)."""
    response = client.messages.create(
        model=model_name,
        system=system_msg or "You are a Dungeon Master for a text RPG.",
        messages=merged,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking={"type": "enabled", "budget_tokens": thinking_budget},
    )
    response_text = None
    thinking = None
    for block in response.content:
        if hasattr(block, "text"):
            if block.type == "thinking":
                thinking = block.text
            elif response_text is None:
                response_text = block.text
    _stop_thinking(thinking_end, thinking_thread)
    if thinking:
        _print_block("  Thinking", thinking.strip(), "dim")
    if response_text:
        _print_block("  Output", response_text.strip())
    return response_text, thinking, thinking_end, thinking_thread


def _stream_anthropic(client, system_msg, merged, temperature, max_tokens,
                      thinking_budget, model_name, thinking_end, thinking_thread):
    """
    Streaming Anthropic call. Prints tokens to stdout as they arrive.
    Thinking content appears in a separate dim block; output in its own block.
    Returns (full_text, full_thinking, thinking_end, thinking_thread).
    """
    stream = client.messages.create(
        model=model_name,
        system=system_msg or "You are a Dungeon Master for a text RPG.",
        messages=merged,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking={"type": "enabled", "budget_tokens": thinking_budget},
        stream=True,
    )
    full_text = ""
    full_thinking = ""
    current_block_type = None

    try:
        for event in stream:
            if event.type == "content_block_start":
                current_block_type = event.content_block.type
            elif event.type == "content_block_delta":
                delta = event.delta
                if delta.type == "thinking_delta":
                    full_thinking += delta.thinking
                elif delta.type == "text_delta":
                    full_text += delta.text
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass

    # Stop thinking animation before printing blocks
    _stop_thinking(thinking_end, thinking_thread)

    # Print blocks after streaming completes
    if full_thinking:
        _print_block("  Thinking", full_thinking.strip(), "dim")
    if full_text:
        _print_block("  Output", full_text.strip())

    return full_text, full_thinking if full_thinking else None, thinking_end, thinking_thread


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Dungeon Master of a rich, immersive, system-agnostic text RPG.

## YOUR ROLE
You are the world, the narrator, and the referee. You describe the world in vivid,
sensory detail and respond to the player's words and actions with engaging narrative.

## CORE PRINCIPLES
1. **You handle ALL mechanics invisibly.** Dice rolls, attribute checks, combat
   initiative, damage calculations, inventory management, health tracking - all
   happen behind the scenes. The player never sees dice, numbers, or mechanical
   notation. You simply narrate the outcome.

2. **The player navigates through natural language only.** They describe what they
   want to do, ask questions, examine things, interact with NPCs, and explore.
   There are no menus, no buttons, no numbered choices. Everything is freeform
   natural language.

3. **You are creative and responsive.** If the player does something unexpected,
   adapt the world to their actions. There are no "wrong" things to try - the
   world responds to whatever the player imagines.

4. **Maintain consistency.** Track the world state, NPC relationships, inventory,
   health, and story progress internally. Reference past events naturally in
   narration.

5. **Pace the story.** Don't resolve everything in one response. Create tension,
   introduce complications, and give the player moments to react. End responses
   with an open prompt that invites the player to continue.

## MECHANICS (INTERNAL - NEVER EXPOSE)
- Attributes (3-18): Strength, Dexterity, Constitution, Intelligence, Wisdom, Charisma
- Health points derived from Constitution
- Simple d20-style checks: roll + attribute modifier vs. difficulty (10=easy, 15=hard, 20=very hard)
- Combat uses initiative (Dexterity-based), attack rolls, and damage
- Inventory tracking with weight limits
- Level progression through adventures

These mechanics are entirely hidden. When the player tries something, you silently
roll the appropriate check and narrate the result. Never mention dice, rolls,
modifiers, difficulties, or any mechanical notation.

## RESPONSE FORMAT
- Respond purely in narrative prose - as if telling a story
- Use second person ("You see...", "You feel...") for the player's perspective
- Use vivid sensory details: sights, sounds, smells, textures, atmosphere
- Keep responses between 150-400 words
- End each response with an implicit or explicit invitation for the player to act
- NEVER use bullet points, numbered lists, mechanical terms, or game-like formatting
- NEVER present choices like "1. Go north, 2. Attack, 3. Talk"
- If the player asks a question, answer in-character as the world narrator

## CHARACTER CREATION
When creating a character, ask the player (in a single message):
1. What is your character's name?
2. What race or species are they? (Human, Elf, Dwarf, or anything they imagine)
3. What is their class or role? (Warrior, Mage, Rogue, Healer, or anything they imagine)
4. Describe their appearance and personality briefly

After they respond, silently assign attributes (3d6 for each), determine health,
and begin the adventure. Place them in an interesting starting scenario that
ties to their character's background.

## WORLD-BUILDING
- Create a rich, living world with history, cultures, and mysteries
- NPCs have their own motivations, personalities, and secrets
- The world changes based on player actions
- Include unexpected events, wandering monsters, and hidden opportunities
- Balance danger with wonder - not everything is combat

## IMPORTANT RULES
1. NEVER break character - you are the Dungeon Master, not a game system
2. NEVER mention that you are an AI, a language model, or a program
3. NEVER reveal internal mechanics, dice, rolls, or statistics
4. NEVER use formatting like "HP: 20/20" or "You roll a 17"
5. If the player tries something impossible, describe why in narrative terms
6. Always keep the story moving - don't let the narrative stall
7. Be generous with creative descriptions and immersive world-building
"""


# ---------------------------------------------------------------------------
# Game state persistence
# ---------------------------------------------------------------------------

def _state_path():
    """Get the path to the game state JSON file."""
    return Path.home() / ".rpg_engine_save.json"


def _load_state():
    """Load game state from JSON file. Returns None if no save exists."""
    path = _state_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def _save_state(state):
    """Save game state to JSON file."""
    path = _state_path()
    state["_saved_at"] = datetime.now().isoformat()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"\n  Could not save game: {e}")


# ---------------------------------------------------------------------------
# Character creation
# ---------------------------------------------------------------------------

def _create_character_prompt():
    """Return the system message for character creation."""
    return """\
You are creating a character for this player. Please ask them these four questions
in a single, warm, inviting message:

1. What is your character's name?
2. What race or species are they? (Human, Elf, Dwarf, or anything they imagine)
3. What is their class or role? (Warrior, Mage, Rogue, Healer, or anything they imagine)
4. Describe their appearance and personality briefly

Make the message feel like a welcoming campfire tale. Do NOT present it as a form.
Write it as if you're a storyteller inviting them to begin their legend.

IMPORTANT: Ask all four questions in a single message. Wait for the player's
response before proceeding.
"""


def _process_character_response(player_input):
    """Process the player's character creation response and generate the starting scenario."""
    # Build messages for the LLM to process character creation
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"CHARACTER_CREATION_RESPONSE: {player_input}"},
    ]
    return messages


# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

class GameEngine:
    """
    The core RPG engine. Manages game state, LLM communication,
    character creation, and the main game loop.
    """

    def __init__(self):
        self.state = _load_state()
        self.messages = []

    def has_saved_game(self):
        """Check if a saved game exists."""
        return self.state is not None

    def load_game(self):
        """Load a saved game and restore conversation history."""
        if self.state:
            raw_messages = self.state.get("messages")
            if not isinstance(raw_messages, list):
                raw_messages = []
            self.messages = raw_messages
            # Ensure system prompt is first
            if not self.messages or self.messages[0].get("role") != "system":
                self.messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
            # Restore world and character info from saved state
            if "world_name" not in self.state:
                self.state["world_name"] = "the Known Realm"
            if "character" not in self.state:
                self.state["character"] = {}
            print(f"\n  World: {self.state.get('world_name', 'the Known Realm')}")
            char = self.state.get('character', {})
            char_name = char.get('name', '').strip() if char else ''
            if not char_name:
                char_name = 'Unknown'
            print(f"  Character: {char_name}")

    def save_game(self):
        """Save the current game state to JSON."""
        if self.state is None:
            self.state = {
                "messages": [],
                "character": {},
                "world_name": "the Known Realm",
                "status": "new",
            }
        self.state["messages"] = self.messages
        _save_state(self.state)

    def create_character(self):
        """Run the character creation flow."""
        # Initialize state if needed
        if self.state is None:
            self.state = {
                "messages": [],
                "character": {},
                "world_name": "the Known Realm",
                "status": "new",
            }

        # Set up initial system prompt
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Get character creation prompt from LLM
        print(_c("  Character Creation", "bold", "magenta"))
        _print_sep("-", "magenta")
        print()

        char_prompt = [
            {"role": "system", "content": _create_character_prompt()},
            {"role": "user", "content": "Please begin character creation."},
        ]

        thinking_end, thinking_thread = _show_thinking(duration=None)
        try:
            dm_questions, dm_reasoning, thinking_end, thinking_thread = _call_llm(char_prompt, temperature=1, max_tokens=4096,
                                                                                   thinking_end=thinking_end, thinking_thread=thinking_thread)
        except KeyboardInterrupt:
            _stop_thinking(thinking_end, thinking_thread)
            print("\n  The Oracle's voice fades as you step away...\n")
            self.save_game()
            return False
        # Store the DM's questions in conversation history
        self.messages.append({"role": "assistant", "content": dm_questions})

        # Wait for player input
        while True:
            try:
                player_input = input("  " + _c("[?]", "yellow") + _c(" Your words... (type 'quit' to exit)", "dim") + _c(">", "green") + " ")
                print()
            except (EOFError, KeyboardInterrupt):
                print("\n  The adventure pauses...\n")
                self.save_game()
                return False

            player_input = player_input.strip()
            if not player_input:
                continue

            if player_input.lower() in ("quit", "exit", "q"):
                print("  Your legend remains unwritten... for now.\n")
                self.save_game()
                return False

            # Process character creation
            print(_c("  Recording your legend...", "dim"))
            print()

            # Build messages including the DM's questions for full context
            char_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "assistant", "content": dm_questions},
                {"role": "user", "content": f"CHARACTER_CREATION_RESPONSE: {player_input}"},
            ]
            thinking_end, thinking_thread = _show_thinking(duration=None)
            try:
                response, char_reasoning, thinking_end, thinking_thread = _call_llm(char_messages, temperature=1, max_tokens=16384,
                                                                                      thinking_end=thinking_end, thinking_thread=thinking_thread)
            except KeyboardInterrupt:
                _stop_thinking(thinking_end, thinking_thread)
                print("\n  The Oracle's voice fades as you step away...\n")
                self.save_game()
                return False

            # Update messages to include the full character creation exchange
            self.messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "assistant", "content": dm_questions},
                {"role": "user", "content": player_input},
                {"role": "assistant", "content": response},
            ]
            if char_reasoning:
                self.state["last_reasoning"] = char_reasoning

            # Extract character info from the LLM response and player input
            self.state["status"] = "playing"
            self.state["character"]["name"] = "the adventurer"
            self.state["character"]["race"] = "unknown"
            self.state["character"]["class"] = "unknown"

            # Try multiple patterns to extract character details from the LLM's narrative
            name_patterns = [
                r'your name is (\w[\w ]*?)(?:[,.\s]|$)',
                r'you are (?:named|called) (\w[\w ]*?)(?:[,.\s]|$)',
                r'(\w[\w ]*?), (?:a|an) (?:brave|young|weary|fierce)',
            ]
            for pattern in name_patterns:
                m = re.search(pattern, response, re.IGNORECASE)
                if m:
                    self.state["character"]["name"] = m.group(1).strip()
                    break

            race_patterns = [
                r'(?:race|blood|kind) is (\w[\w ]*?)(?:[,.\s]|$)',
                r'(?:a|an) (\w[\w ]*?)(?:\s+by\s+race|\s+by\s+kind|\s+by\s+blood)',
                r'you are (?:a|an) (\w[\w ]*?)(?:\s+(?:warrior|mage|rogue|healer|hunter|knight|scholar|wanderer))',
            ]
            for pattern in race_patterns:
                m = re.search(pattern, response, re.IGNORECASE)
                if m:
                    self.state["character"]["race"] = m.group(1).strip()
                    break

            class_patterns = [
                r'(?:class|role|vocation) is (\w[\w ]*?)(?:[,.\s]|$)',
                r'(?:a|an) (\w[\w ]*?)(?:\s+(?:of|who|with|named|called))',
                r'you are (?:a|an) (\w[\w ]*?)(?:\s+(?:who|with|named|called|of))',
            ]
            for pattern in class_patterns:
                m = re.search(pattern, response, re.IGNORECASE)
                if m:
                    self.state["character"]["class"] = m.group(1).strip()
                    break

            # Fallback: try to extract from the player's original input
            if self.state["character"]["name"] == "the adventurer":
                name_match = re.search(r'(?:my name is|i am (?:named|called|going by))\s+(\w[\w ]*?)\b', player_input, re.IGNORECASE)
                if name_match:
                    self.state["character"]["name"] = name_match.group(1).strip()

            if self.state["character"]["race"] == "unknown":
                race_match = re.search(r'(?:i am (?:a|an)|my (?:race|blood|kind) is)\s+(\w[\w ]*?)\b', player_input, re.IGNORECASE)
                if race_match:
                    self.state["character"]["race"] = race_match.group(1).strip()

            if self.state["character"]["class"] == "unknown":
                class_match = re.search(r'(?:i am (?:a|an)|my (?:class|role|vocation) is)\s+(\w[\w ]*?)\b', player_input, re.IGNORECASE)
                if class_match:
                    self.state["character"]["class"] = class_match.group(1).strip()

            self.save_game()
            print(_c("  Your legend begins...", "bold", "green"))
            _print_sep("-", "green")
            print()
            return True

    def game_loop(self):
        """The main game loop - player input -> LLM -> response -> save."""
        print(_c("  " + "=" * 58, "cyan"))
        print(_c("  Type anything. The world listens.", "dim"))
        print(_c("  " + "=" * 58, "cyan"))
        print()

        while True:
            try:
                player_input = input("  " + _c("[?]", "yellow") + _c(" What do you do?", "dim") + _c(">", "green") + " ")
            except (EOFError, KeyboardInterrupt):
                print("\n\n  The adventure pauses as you step away...")
                print("  Your journey is saved. Until next time.\n")
                self.save_game()
                break

            player_input = player_input.strip()
            if not player_input:
                continue

            if player_input.lower() in ("quit", "exit", "q"):
                print("\n  Your legend pauses here...")
                print("  Your journey is saved. Until next time.\n")
                self.save_game()
                break

            if player_input.lower() in ("save",):
                self.save_game()
                print("  Adventure saved.\n")
                continue

            if player_input.lower() in ("status",):
                self._show_status()
                continue

            if player_input.lower() in ("help", "?", "h"):
                self._show_help()
                continue

            if player_input.lower() in ("newgame", "new game"):
                if input("  Are you sure? This will start a brand new adventure. (yes/no): ").strip().lower() in ("yes", "y"):
                    save_path = _state_path()
                    if save_path.exists():
                        save_path.unlink()
                    self.state = None
                    print("  A new world awaits. Let us begin.\n")
                    if not self.create_character():
                        return
                    print()
                continue

            # Send to LLM
            self.messages.append({"role": "user", "content": player_input})

            thinking_end, thinking_thread = _show_thinking(duration=None)
            try:
                response, reasoning, thinking_end, thinking_thread = _call_llm(self.messages, temperature=1, max_tokens=16384,
                                                                                 thinking_end=thinking_end, thinking_thread=thinking_thread)
            except KeyboardInterrupt:
                _stop_thinking(thinking_end, thinking_thread)
                print("\n  The Oracle's voice fades as you step away...\n")
                # Remove the user message that had no response
                self.messages.pop()
                self.save_game()
                continue

            self.messages.append({"role": "assistant", "content": response})
            if reasoning:
                self.state["last_reasoning"] = reasoning

            # Keep messages manageable - remove oldest user messages beyond system prompt
            # but keep the last 100 messages for context (model supports 262k tokens)
            if len(self.messages) > 104:
                # Keep system + last 103 messages
                self.messages = [self.messages[0]] + self.messages[-103:]

            print()

            # Auto-save after each turn
            self.save_game()

    def _show_status(self):
        """Display current game status."""
        if self.state is None:
            print("  Status: No game loaded.")
            return
        print(_c("  +-- Status ------------------------------------------", "bold", "cyan"))
        print(_c("  |", "cyan"))

        char = self.state.get("character", {})
        name = char.get("name", "").strip() if char else ""
        race = char.get("race", "").strip() if char else ""
        cls = char.get("class", "").strip() if char else ""
        print(_c("  |  Name:     " + (name or "Unknown"), "cyan"))
        print(_c("  |  Race:     " + (race or "Unknown"), "cyan"))
        print(_c("  |  Class:    " + (cls or "Unknown"), "cyan"))
        print(_c("  |", "cyan"))

        # Count messages to estimate turns
        turn_count = sum(1 for m in self.messages if m.get("role") == "user")
        print(_c("  |  Turns:    " + str(turn_count), "cyan"))
        print(_c("  |", "cyan"))

        # Show reasoning/thinking content if available
        reasoning = self.state.get("last_reasoning")
        if reasoning:
            display_reasoning = reasoning if len(reasoning) <= 200 else reasoning[:200] + "..."
            print(_c("  |  Thinking: " + _c(display_reasoning.strip()[:180], "dim"), "cyan"))
            print(_c("  |", "cyan"))

        if self.state.get("_saved_at"):
            print(_c("  |  Saved:    " + self.state["_saved_at"][:19], "cyan"))

        print(_c("  +-- Status ------------------------------------------", "bold", "cyan"))
        print()

    def _show_help(self):
        """Display help information."""
        _print_sep("-", "cyan")
        print(f"  {_c('Available commands:', 'bold')}")
        print()
        print(f"  {_c('quit', 'yellow')}      - Save and exit the adventure")
        print(f"  {_c('save', 'yellow')}     - Manually save the current game")
        print(f"  {_c('status', 'yellow')} - Show character and game status")
        print(f"  {_c('newgame', 'yellow')}  - Start a brand new adventure")
        print(f"  {_c('help', 'yellow')}   - Show this help message")
        print()
        print(f"  {_c('Tip:', 'bold')} Everything else is roleplay! Describe actions,")
        print(f"  ask questions, talk to NPCs, examine things - the world responds to")
        print(f"  your words. No menus, no choices, just your imagination.")
        _print_sep("-", "cyan")
        print()


