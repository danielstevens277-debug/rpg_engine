#!/usr/bin/env python3
"""
RPG Engine - Auto-Play Mode
=============================
The LLM plays both the Dungeon Master and the player character,
swapping back and forth to generate a self-directed story.

Each role has its own separate context, thinking block, and output block.

Usage:
    python autoplay.py              # Continue from saved game (sandbox mode)
    python autoplay.py --new         # Start a fresh game
    python autoplay.py --turns N     # Limit to N turns (default: 50)
    python autoplay.py --char-choice # Choose character mode at startup
    python autoplay.py --no-pause    # Uninterrupted autoplay (no sandbox pauses)

Sandbox Mode (default):
    After each turn, you can:
      - Press Enter to continue autoplay
      - 'a' to add an event or being to the world
      - 'r' to remove an event or being from the world
      - 'w' to write your character's next action directly
"""

import argparse
import re
import sys
import os

# ---------------------------------------------------------------------------
# Engine import (supports both python autoplay.py and python rpg_engine/autoplay.py)
# ---------------------------------------------------------------------------

def _import_game_engine():
    try:
        from engine import (GameEngine, _c, _state_path, SYSTEM_PROMPT,
                            _call_llm, _show_thinking, _stop_thinking,
                            _stream_block_begin, _stream_block_end)
        return (GameEngine, _c, _state_path, SYSTEM_PROMPT, _call_llm,
                _show_thinking, _stop_thinking, _stream_block_begin,
                _stream_block_end)
    except ImportError:
        pass
    try:
        from rpg_engine.engine import (GameEngine, _c, _state_path, SYSTEM_PROMPT,
                                       _call_llm, _show_thinking, _stop_thinking,
                                       _stream_block_begin, _stream_block_end)
        return (GameEngine, _c, _state_path, SYSTEM_PROMPT, _call_llm,
                _show_thinking, _stop_thinking, _stream_block_begin,
                _stream_block_end)
    except ImportError:
        pass
    engine_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.py")
    if os.path.isfile(engine_path):
        import importlib.util
        try:
            spec = importlib.util.spec_from_file_location("engine", engine_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {engine_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return (mod.GameEngine, mod._c, mod._state_path, mod.SYSTEM_PROMPT,
                    mod._call_llm, mod._show_thinking, mod._stop_thinking,
                    mod._stream_block_begin, mod._stream_block_end)
        except Exception as e:
            print(f"  Failed to load engine module: {e}")
            sys.exit(1)
    print("  Could not find engine.py. Make sure you are running from the rpg_engine/ directory.")
    sys.exit(1)


(GameEngine, _c, _state_path, SYSTEM_PROMPT, _call_llm,
 _show_thinking, _stop_thinking, _stream_block_begin, _stream_block_end) = \
    _import_game_engine()

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def _print_sep(char="=", color="cyan", width=62):
    print(_c(char * width, color))


_BLOCK_SEP = "\u2500" * 58


def _print_thinking_block(title, text):
    """Print a thinking block for either player or DM (non-streaming fallback)."""
    print()
    print(_c(_BLOCK_SEP, "dim"))
    print(_c(f"  {title}", "dim"))
    print(_c(_BLOCK_SEP, "dim"))
    print(_c(text.strip(), "dim"))
    print(_c(_BLOCK_SEP, "dim"))


def _print_output_block(title, text):
    """Print a titled output block (non-streaming fallback)."""
    print()
    print(_c(_BLOCK_SEP, "cyan"))
    print(_c(f"  {title}", "cyan"))
    print(_c(_BLOCK_SEP, "cyan"))
    print(_c(text.strip(), "cyan"))
    print(_c(_BLOCK_SEP, "cyan"))


def _print_player_action(action):
    """Print the player character's action in a styled block."""
    print()
    print(_c(_BLOCK_SEP, "green"))
    print(_c("  \u2694 PLAYER", "bold", "green"))
    print(_c(_BLOCK_SEP, "green"))
    print(_c(action.strip(), "green"))
    print(_c(_BLOCK_SEP, "green"))


def _print_dm_response(response):
    """Print the DM's narrative in a styled block."""
    print()
    print(_c(_BLOCK_SEP, "cyan"))
    print(_c("  Dungeon Master", "cyan"))
    print(_c(_BLOCK_SEP, "cyan"))
    print(_c(response.strip(), "cyan"))
    print(_c(_BLOCK_SEP, "cyan"))


# ---------------------------------------------------------------------------
# Streaming LLM caller for autoplay
# ---------------------------------------------------------------------------
# This is now handled by _call_llm from engine.py


# ---------------------------------------------------------------------------
# Character description helpers
# ---------------------------------------------------------------------------

def _generate_character_description():
    """
    Ask the LLM to generate a compelling character description for auto-play.
    Returns a dict with keys: name, race, class, appearance.
    """
    _print_sep("-", "magenta")
    print(_c("  Character Creation (AI-generated)", "bold", "magenta"))
    print()

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a creative storyteller. Generate a compelling fantasy character "
                "description. Respond with exactly this format:\n\n"
                "Name: [character name]\n"
                "Race: [race/species]\n"
                "Class: [class/role]\n"
                "Description: [2-3 sentences describing appearance, personality, and a hint of backstory]\n\n"
                "Make it vivid and interesting. The character should feel alive and ready for adventure."
            ),
        },
        {"role": "user", "content": "Generate a fantasy character for an RPG auto-play adventure."},
    ]

    print(_c("  The Oracle crafts a character...", "dim"))
    response, reasoning, thinking_end, thinking_thread = _call_llm(
        prompt, temperature=1.0, max_tokens=1024, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if reasoning:
        _print_thinking_block("  Thinking", reasoning)
    _print_output_block("Character Description", response)

    # Parse the response
    info = {"name": "", "race": "unknown", "class": "unknown", "appearance": response.strip()}

    name_m = re.search(r"Name:\s*(.+)", response, re.IGNORECASE)
    if name_m:
        info["name"] = name_m.group(1).strip()

    race_m = re.search(r"Race:\s*(.+)", response, re.IGNORECASE)
    if race_m:
        info["race"] = race_m.group(1).strip()

    class_m = re.search(r"Class:\s*(.+)", response, re.IGNORECASE)
    if class_m:
        info["class"] = class_m.group(1).strip()

    return info


def _collect_character_description():
    """
    Let the user provide their own character description.
    Returns a dict with keys: name, race, class, appearance.
    """
    _print_sep("-", "magenta")
    print(_c("  Character Creation (your description)", "bold", "magenta"))
    print()
    print(_c("Describe your character. Include their name, race, class,", "dim"))
    print(_c("appearance, and a hint of personality.", "dim"))
    print()

    lines = []
    while True:
        try:
            line = input("  " + _c(">", "green") + " ")
        except (EOFError, KeyboardInterrupt):
            print("\n  Your legend remains unwritten... for now.\n")
            sys.exit(0)
        lines.append(line)
        if line.strip():
            break

    while True:
        try:
            line = input("  " + _c("  ", "dim") + " ")
        except (EOFError, KeyboardInterrupt):
            break
        if not line.strip():
            break
        lines.append(line)

    description = "\n".join(lines).strip()
    if not description:
        description = "A mysterious wanderer with a quiet presence and sharp eyes."

    info = {"name": "", "race": "unknown", "class": "unknown", "appearance": description}

    name_m = re.search(
        r"(?:my name is|i am(?:\s+(?:named|called|going by))?)\s+(\w[\w ]*?)\b",
        description, re.IGNORECASE,
    )
    if name_m:
        info["name"] = name_m.group(1).strip()

    race_m = re.search(
        r"(?:i am (?:a|an)|my (?:race|blood|kind))\s+([a-zA-Z]+)",
        description, re.IGNORECASE,
    )
    if race_m:
        info["race"] = race_m.group(1).strip()

    class_m = re.search(
        r"(?:i am (?:a|an)|my (?:class|role|vocation|calling))\s+([a-zA-Z]+)",
        description, re.IGNORECASE,
    )
    if class_m:
        info["class"] = class_m.group(1).strip()

    print()
    print(_c("  Character recorded:", "bold", "green"))
    print(_c(f"    Name:     {info['name'] or 'Unknown'}", "green"))
    print(_c(f"    Race:     {info['race']}", "green"))
    print(_c(f"    Class:    {info['class']}", "green"))
    print()
    return info


def _choose_character_mode():
    """
    Ask the user how they want to create the character:
    1. AI generates a character
    2. User provides their own description
    Returns 'ai' or 'user'.
    """
    print(_c("  How shall your character be born?", "bold", "magenta"))
    print()
    print(_c("  [1]", "green") + " Let the Oracle craft a character for you")
    print(_c("  [2]", "green") + " Describe your character yourself")
    print()
    while True:
        try:
            choice = input("  " + _c(">", "green") + " ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  The adventure fades... until next time.\n")
            sys.exit(0)
        if choice in ("1", "ai", "a"):
            return "ai"
        elif choice in ("2", "manual", "m", "user"):
            return "user"
        elif choice in ("q", "quit", "exit"):
            print("\n  Your legend remains unwritten... for now.\n")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Auto-play prompts
# ---------------------------------------------------------------------------

def _build_player_prompt(engine):
    """
    Build the system prompt for the LLM acting as the player character.
    """
    char = engine.state.get("character", {}) if engine.state else {}
    char_name = char.get("name", "the adventurer").strip()
    char_race = char.get("race", "unknown").strip()
    char_class = char.get("class", "unknown").strip()
    char_appearance = char.get("appearance", "").strip()

    identity = f"You are **{char_name}**, a {char_race} {char_class}."
    if char_appearance:
        identity += f" {char_appearance}"

    return f"""\
{identity}

You are the PLAYER character in this RPG. The Dungeon Master narrates the world,
and you decide what your character does next.

## YOUR JOB
Decide what your character does, says, or thinks. Be proactive, curious, and
creative. Drive the story forward with meaningful actions.

## RULES
- Write in first person ("I draw my sword", "I ask the merchant...") or third person
  ("Kaelen draws his sword", "She asks the merchant...") -- pick one style and stick to it
- Be vivid and specific about actions, dialogue, and thoughts
- Show personality: be brave, cautious, clever, or reckless as fits your character
- End with a clear action or question that the world can respond to
- Keep it to 2-4 sentences -- enough to be interesting, not so much that it steals the DM's role
- NEVER describe the world, NPCs, or outcomes -- only your character's actions and words
- NEVER break character or mention you are an AI
- NEVER use mechanical terms (dice, rolls, HP, etc.)

## CURRENT SITUATION
"""


def _build_dm_prompt():
    """
    Return the DM system prompt, adapted for auto-play mode.
    """
    return SYSTEM_PROMPT + """

## AUTO-PLAY MODE
The player character is controlled by an AI. When responding:
- Keep your narration engaging and open-ended
- Present clear situations that invite action
- Don't resolve the player's actions for them -- let the AI player respond
- Maintain the same narrative quality as if a human were playing

## SANDBOX MODE
The human watching this adventure may occasionally intervene to add events,
remove beings, or direct the player character's actions. When they do:
- Acknowledge their additions naturally within the narrative
- Treat removals as events the world responds to
- If the player character does something unexpected due to intervention,
  adapt the world accordingly
- Never break immersion or acknowledge the sandbox mechanics directly
"""


# ---------------------------------------------------------------------------
# Auto-play character creation
# ---------------------------------------------------------------------------

def autoplay_character_creation(engine, char_info):
    """
    Run auto-play character creation. The LLM asks questions, answers them
    as the player, and generates the starting scenario.
    """
    _print_sep("-", "magenta")
    print(_c("  Character Creation (auto)", "bold", "magenta"))
    print()

    # Step 1: DM asks character creation questions
    char_prompt = [
        {
            "role": "system",
            "content": (
                "You are creating a character for this player. Please ask them these four questions "
                "in a single, warm, inviting message:\n\n"
                "1. What is your character's name?\n"
                "2. What race or species are they?\n"
                "3. What is their class or role?\n"
                "4. Describe their appearance and personality briefly\n\n"
                "Make the message feel like a welcoming campfire tale."
            ),
        },
        {"role": "user", "content": "Please begin character creation."},
    ]

    print(_c("  The Dungeon Master prepares the first questions...", "dim"))
    dm_questions, dm_reasoning, thinking_end, thinking_thread = _call_llm(
        char_prompt, temperature=1.0, max_tokens=512, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if dm_reasoning:
        _print_thinking_block("  Thinking", dm_reasoning)
    _print_output_block("Dungeon Master", dm_questions)

    engine.messages = [{"role": "assistant", "content": dm_questions}]

    # Step 2: Generate player's response using the provided character info
    player_response = (
        f"My name is {char_info.get('name', 'the adventurer')}. "
        f"I am a {char_info.get('race', 'unknown')} {char_info.get('class', 'unknown')}. "
        f"{char_info.get('appearance', 'I stand ready for adventure.')} "
        f"I'm here to answer your questions about myself."
    )

    _print_player_action(player_response)
    engine.messages.append({"role": "user", "content": player_response})

    # Step 3: DM generates starting scenario
    char_messages = [
        {"role": "system", "content": _build_dm_prompt()},
        {"role": "assistant", "content": dm_questions},
        {"role": "user", "content": f"CHARACTER_CREATION_RESPONSE: {player_response}"},
    ]

    print(_c("  The world takes shape...", "dim"))
    response, reasoning, thinking_end, thinking_thread = _call_llm(
        char_messages, temperature=0.85, max_tokens=2048, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if reasoning:
        _print_thinking_block("  Thinking", reasoning)
    _print_dm_response(response)

    # Update messages
    engine.messages = [
        {"role": "system", "content": _build_dm_prompt()},
        {"role": "assistant", "content": dm_questions},
        {"role": "user", "content": player_response},
        {"role": "assistant", "content": response},
    ]

    # Initialize state
    engine.state = {
        "messages": engine.messages,
        "character": char_info,
        "world_name": "the Known Realm",
        "status": "playing",
    }
    engine.save_game()


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

def _sandbox_add_event(engine, description):
    """
    Ask the DM to acknowledge and weave an added event into the story.
    The DM narrates the event, then the player character reacts.
    """
    print()
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c("  ✨ SANDBOX: Event Added", "bold", "magenta"))
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c(f"  {description}", "dim"))
    print()

    # Ask DM to incorporate the event
    messages = [
        {"role": "system", "content": _build_dm_prompt()},
    ]
    messages.extend(engine.messages)
    messages.append({
        "role": "user",
        "content": (
            f"AN EVENT HAS OCCURRED: {description}\n\n"
            "Narrate this event as it unfolds in the world. Describe what happens "
            "and how the environment and any present characters react. End by "
            "leaving the player character with an opportunity to respond."
        ),
    })

    print(_c("  The Dungeon Master weaves the new thread into the tale...", "dim"))
    dm_response, dm_reasoning, thinking_end, thinking_thread = _call_llm(
        messages, temperature=0.85, max_tokens=2048, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if dm_reasoning:
        _print_thinking_block("  Thinking", dm_reasoning)
    _print_dm_response(dm_response)

    engine.messages.append({"role": "assistant", "content": dm_response})

    # Player character reacts
    player_messages = [
        {"role": "system", "content": _build_player_prompt(engine)},
    ]
    player_messages.extend(engine.messages)

    player_response, player_reasoning, thinking_end, thinking_thread = _call_llm(
        player_messages, temperature=0.9, max_tokens=1024, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if player_reasoning:
        _print_thinking_block("  Thinking", player_reasoning)
    _print_player_action(player_response)

    engine.messages.append({"role": "user", "content": player_response})
    engine.save_game()


def _sandbox_remove_element(engine, description):
    """
    Ask the DM to narrate the removal of a being or event from the story.
    """
    print()
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c("  ✖ SANDBOX: Element Removed", "bold", "magenta"))
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c(f"  {description}", "dim"))
    print()

    messages = [
        {"role": "system", "content": _build_dm_prompt()},
    ]
    messages.extend(engine.messages)
    messages.append({
        "role": "user",
        "content": (
            f"SOMETHING HAS BEEN REMOVED: {description}\n\n"
            "Narrate this removal as an event in the world. Describe what happens "
            "as this being or event fades from existence and how the world reacts. "
            "End by leaving the player character with an opportunity to respond."
        ),
    })

    print(_c("  The Dungeon Master weaves the thread back into silence...", "dim"))
    dm_response, dm_reasoning, thinking_end, thinking_thread = _call_llm(
        messages, temperature=0.85, max_tokens=2048, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if dm_reasoning:
        _print_thinking_block("  Thinking", dm_reasoning)
    _print_dm_response(dm_response)

    engine.messages.append({"role": "assistant", "content": dm_response})

    # Player character reacts
    player_messages = [
        {"role": "system", "content": _build_player_prompt(engine)},
    ]
    player_messages.extend(engine.messages)

    player_response, player_reasoning, thinking_end, thinking_thread = _call_llm(
        player_messages, temperature=0.9, max_tokens=1024, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if player_reasoning:
        _print_thinking_block("  Thinking", player_reasoning)
    _print_player_action(player_response)

    engine.messages.append({"role": "user", "content": player_response})
    engine.save_game()


def _sandbox_write_action(engine, action):
    """
    Let the user write their own character action, then have the DM respond.
    """
    print()
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c("  ⚔ SANDBOX: Your Character Acts", "bold", "magenta"))
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c(f"  {action}", "green"))
    print()

    # Add user's action as the player's turn
    engine.messages.append({"role": "user", "content": action})

    # DM responds
    messages = [
        {"role": "system", "content": _build_dm_prompt()},
    ]
    messages.extend(engine.messages)

    print(_c("  The Dungeon Master responds...", "dim"))
    dm_response, dm_reasoning, thinking_end, thinking_thread = _call_llm(
        messages, temperature=0.85, max_tokens=2048, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if dm_reasoning:
        _print_thinking_block("  Thinking", dm_reasoning)
    _print_dm_response(dm_response)

    engine.messages.append({"role": "assistant", "content": dm_response})

    # AI player character then reacts
    player_messages = [
        {"role": "system", "content": _build_player_prompt(engine)},
    ]
    player_messages.extend(engine.messages)

    player_response, player_reasoning, thinking_end, thinking_thread = _call_llm(
        player_messages, temperature=0.9, max_tokens=1024, stream=True
    )
    _stop_thinking(thinking_end, thinking_thread)

    if player_reasoning:
        _print_thinking_block("  Thinking", player_reasoning)
    _print_player_action(player_response)

    engine.messages.append({"role": "user", "content": player_response})
    engine.save_game()


def _pause_for_sandbox(engine):
    """
    Pause the autoplay loop and present sandbox options to the user.
    Returns True if the user wants to continue autoplay, False to exit.
    """
    print(_c(_BLOCK_SEP, "cyan"))
    print(_c("  ◆ Turn complete. What would you like to do?", "bold", "cyan"))
    print(_c(_BLOCK_SEP, "cyan"))
    print()
    print(_c("  [Enter]", "green") + "  Continue the adventure")
    print(_c("  [a]", "green") + "     Add an event or being (describe it)")
    print(_c("  [r]", "green") + "     Remove an event or being (describe it)")
    print(_c("  [w]", "green") + "     Write your character's next action")
    print(_c("  [q]", "green") + "     Quit and save")
    print()

    while True:
        try:
            choice = input("  " + _c(">", "green") + " ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_c("  The adventure pauses as you step away...", "bold", "yellow"))
            engine.save_game()
            return False

        if not choice:
            # Continue autoplay
            return True
        elif choice in ("a", "add"):
            try:
                description = input("  " + _c(">", "green") + " Describe the event or being: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                print(_c("  The adventure pauses as you step away...", "bold", "yellow"))
                engine.save_game()
                return False
            if description:
                _sandbox_add_event(engine, description)
            continue
        elif choice in ("r", "remove"):
            try:
                description = input("  " + _c(">", "green") + " Describe what to remove: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                print(_c("  The adventure pauses as you step away...", "bold", "yellow"))
                engine.save_game()
                return False
            if description:
                _sandbox_remove_element(engine, description)
            continue
        elif choice in ("w", "write"):
            try:
                description = input("  " + _c(">", "green") + " What does your character do: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                print(_c("  The adventure pauses as you step away...", "bold", "yellow"))
                engine.save_game()
                return False
            if description:
                _sandbox_write_action(engine, description)
            continue
        elif choice in ("q", "quit", "exit"):
            return False
        else:
            print(_c("  Unknown command. Press Enter to continue, or a/r/w/q.", "dim"))


# ---------------------------------------------------------------------------
# Auto-play game loop
# ---------------------------------------------------------------------------

def autoplay_game_loop(engine, max_turns=50, sandbox=True):
    """
    Run the auto-play game loop. The LLM alternates between:
    1. Dungeon Master role (narrating the world)
    2. Player character role (deciding what to do next)

    Each turn consists of a DM response followed by a player response.

    After each turn, the user may pause to add/remove events and beings
    or write their own character actions (sandbox mode).

    Parameters:
        engine: GameEngine instance with state and messages already set up
        max_turns: Maximum number of DM-player pairs to generate (default: 50)
        sandbox: If True, pause after each turn for sandbox commands
                 (default: True)
    """
    mode_label = "Auto-Play + Sandbox" if sandbox else "Auto-Play"
    _print_sep("=", "cyan")
    print(_c(f"  {mode_label}", "bold", "cyan"))
    print(_c(f"  The Oracle directs both player and world (up to {max_turns} turns)", "dim"))
    if sandbox:
        print(_c("  Press Enter to continue, or a/r/w to shape the story", "dim"))
    print(_c(_BLOCK_SEP, "cyan"))
    print()

    player_prompt = _build_player_prompt(engine)
    dm_prompt = _build_dm_prompt()

    turn = 0
    try:
        # Determine who should start based on the last message in history
        # If the last message was from the assistant (DM), the AI player should go first.
        # If the last message was from the user (Player), the DM should go first.
        start_with_dm = True
        if engine.messages:
            last_msg = engine.messages[-1]
            if last_msg.get("role") == "assistant":
                start_with_dm = False

        while turn < max_turns:
            if not start_with_dm:
                # --- PLAYER TURN FIRST ---
                print(_c("  Your character considers their next move...", "dim"))
                print()

                # Build player messages: system (identity) + conversation history
                player_messages = [
                    {"role": "system", "content": player_prompt},
                ]
                player_messages.extend(engine.messages)

                player_response, player_reasoning, thinking_end, thinking_thread = _call_llm(
                    player_messages, temperature=0.9, max_tokens=1024, stream=True
                )
                _stop_thinking(thinking_end, thinking_thread)

                if player_reasoning:
                    _print_thinking_block("  Thinking", player_reasoning)
                _print_player_action(player_response)

                # Add player response to conversation history
                engine.messages.append({"role": "user", "content": player_response})
                
                # Now we can proceed to the normal DM -> Player cycle
                start_with_dm = True

            # --- DUNGEON MASTER TURN ---
            turn += 1
            print(_c(f"  \u25C6 Turn {turn}/{max_turns}", "bold", "yellow"))
            print()

            # Build DM messages: system + conversation history
            dm_messages = [
                {"role": "system", "content": dm_prompt},
            ]
            dm_messages.extend(engine.messages)

            print(_c("  The Dungeon Master contemplates...", "dim"))
            dm_response, dm_reasoning, thinking_end, thinking_thread = _call_llm(
                dm_messages, temperature=0.85, max_tokens=2048, stream=True
            )
            _stop_thinking(thinking_end, thinking_thread)

            if dm_reasoning:
                _print_thinking_block("  Thinking", dm_reasoning)
            _print_dm_response(dm_response)

            # Check if DM's response ends the adventure
            if _is_adventure_ending(dm_response):
                print(_c("  \u25C6 The story reaches its conclusion.", "bold", "magenta"))
                print()
                break

            # Add DM response to conversation history
            engine.messages.append({"role": "assistant", "content": dm_response})

            # --- PLAYER TURN ---
            print(_c("  Your character considers their next move...", "dim"))
            print()

            # Build player messages: system (identity) + conversation history
            player_messages = [
                {"role": "system", "content": player_prompt},
            ]
            player_messages.extend(engine.messages)

            player_response, player_reasoning, thinking_end, thinking_thread = _call_llm(
                player_messages, temperature=0.9, max_tokens=1024, stream=True
            )
            _stop_thinking(thinking_end, thinking_thread)

            if player_reasoning:
                _print_thinking_block("  Thinking", player_reasoning)
            _print_player_action(player_response)

            # Add player response to conversation history
            engine.messages.append({"role": "user", "content": player_response})


            # Keep conversation manageable based on model context limit
            ctx_limit = engine._get_current_context_limit()
            # Estimate tokens: roughly 4 characters per token.
            # Leave 8k tokens for system prompt and response.
            max_prompt_chars = (ctx_limit - 8192) * 4

            total_chars = 0
            keep_idx = 0
            # Always keep the system prompt
            if engine.messages:
                total_chars += len(engine.messages[0].get("content", ""))

            # Count characters from newest to oldest
            for i in range(len(engine.messages) - 1, 0, -1):
                msg_len = len(engine.messages[i].get("content", ""))
                if total_chars + msg_len > max_prompt_chars:
                    keep_idx = i + 1
                    break
                total_chars += msg_len

            if keep_idx > 1:
                engine.messages = [engine.messages[0]] + engine.messages[keep_idx:]

            # Auto-save after each complete turn
            engine.save_game()

            # Progress indicator between turns
            if turn < max_turns:
                print(_c(f"  \u25CB {turn}/{max_turns} turns complete", "dim"))
                print()

            # Sandbox pause after each turn (unless disabled)
            if sandbox and turn < max_turns:
                print(_c(_BLOCK_SEP, "dim"))
                should_continue = _pause_for_sandbox(engine)
                if not should_continue:
                    break
                print()

    except (KeyboardInterrupt, SystemExit):
        print()
        print(_c("  The adventure pauses as you step away...", "bold", "yellow"))
        engine.save_game()
        return
    except Exception as e:
        print()
        print(_c(f"  The Oracle stumbles: {str(e)[:200]}", "red"))
        print(_c("  The adventure has been saved.", "dim"))
        engine.save_game()
        return

    # Adventure complete
    print(_c(_BLOCK_SEP, "magenta"))
    print(_c("  \u25C6 The story comes to a close.", "bold", "magenta"))
    print(_c(_BLOCK_SEP, "magenta"))
    print()
    print(_c(f"  {max_turns} turns of auto-play complete.", "bold", "green"))
    print(_c("  Your adventure has been saved. Resume anytime.", "dim"))
    print()


def _is_adventure_ending(response):
    """
    Check if the DM's response suggests the adventure is concluding.
    Looks for narrative closure indicators.
    """
    response_lower = response.lower()
    closure_indicators = [
        "and so your story ends",
        "and so the tale concludes",
        "the end of your story",
        "thus ends your journey",
        "your legend is complete",
        "and that is the end",
        "the curtain falls",
        "fin",
        "to be continued",
    ]
    for indicator in closure_indicators:
        if indicator in response_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _print_banner():
    """Print the autoplay banner."""
    banner = r"""
======================================================================

      +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
      |  RPG ENGINE - AUTO-PLAY MODE                                   |
      |                                                              |
      |  "The Oracle plays both sides of the tale."                  |
      |                                                              |
      +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+

======================================================================
"""
    print(banner)


def main():
    """Main entry point for autoplay mode."""
    _print_banner()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="RPG Engine - Auto-Play Mode (LLM plays both DM and player)",
        add_help=True,
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh game instead of continuing from a save",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=50,
        help="Maximum number of DM-player turns (default: 50)",
    )
    parser.add_argument(
        "--char-choice",
        action="store_true",
        help="Choose character creation mode at startup (AI-generated or manual)",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Run uninterrupted autoplay without sandbox pauses after each turn",
    )
    args = parser.parse_args()

    # Validate turns
    if args.turns < 1:
        print(_c("  Error: --turns must be at least 1.", "red"))
        sys.exit(1)

    engine = GameEngine()

    # --- Character creation ---
    char_info = None

    if args.new:
        # New game: create character
        if args.char_choice:
            mode = _choose_character_mode()
            if mode == "ai":
                char_info = _generate_character_description()
            else:
                char_info = _collect_character_description()
        else:
            # Default: AI generates character
            char_info = _generate_character_description()

        autoplay_character_creation(engine, char_info)
        print()

    elif engine.has_saved_game():
        # Continue from saved game
        print(_c("  A previous auto-play adventure was found.", "bold", "cyan"))
        char = engine.state.get("character", {})
        char_name = char.get("name", "Unknown").strip() if char else "Unknown"
        if not char_name:
            char_name = "Unknown"
        print(_c(f"  Character: {_c(char_name, 'cyan', 'bold')}", "cyan"))
        print()
        print(_c("  [1]", "green") + " Continue auto-play from where you left off")
        print(_c("  [2]", "green") + " Start a new adventure")
        print(_c("  [q]", "green") + " Quit")
        print()

        while True:
            try:
                choice = input("  " + _c(">", "green") + " ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  The adventure fades... until next time.\n")
                return

            if choice in ("q", "quit", "exit"):
                print("  Your legend remains unwritten... for now.\n")
                return
            if choice == "2":
                # Remove old save before starting new
                save_path = _state_path()
                if save_path.exists():
                    save_path.unlink()
                engine.state = None
                print(_c("  A new world awaits. Let us begin.", "bold", "green"))
                print()
                if args.char_choice:
                    mode = _choose_character_mode()
                    if mode == "ai":
                        char_info = _generate_character_description()
                    else:
                        char_info = _collect_character_description()
                else:
                    char_info = _generate_character_description()
                autoplay_character_creation(engine, char_info)
                print()
                break
            elif choice == "1":
                # Continue existing game
                engine.load_game()
                print(_c("  Resuming your adventure...", "bold", "cyan"))
                print()
                break
            else:
                print(_c("  Please enter 1, 2, or q.", "dim"))

    else:
        # No save, no --new flag: start fresh with AI character
        print(_c("  No saved adventure found. Starting fresh.", "dim"))
        char_info = _generate_character_description()
        autoplay_character_creation(engine, char_info)
        print()

    # --- Game loop ---
    sandbox = not args.no_pause
    autoplay_game_loop(engine, max_turns=args.turns, sandbox=sandbox)


if __name__ == "__main__":
    main()
