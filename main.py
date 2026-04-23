#!/usr/bin/env python3
"""
Conversational Terminal RPG Engine
===================================
A pure natural-language RPG where an LLM acts as a system-agnostic
Dungeon Master. All mechanics (dice rolls, checks, combat, inventory)
are handled invisibly by the LLM. The player navigates the world entirely
through natural language questions and actions - no menus, no buttons.
"""

import sys
import os

# Resolve the engine module relative to this file's location
def _import_game_engine():
    """Import GameEngine, supporting both 'python main.py' and 'python rpg_engine/main.py'."""
    # 1. Try bare import (works when run from inside rpg_engine/)
    try:
        from engine import GameEngine
        return GameEngine
    except ImportError:
        pass

    # 2. Try package import (works when rpg_engine/ is on the path)
    try:
        from rpg_engine.engine import GameEngine
        return GameEngine
    except ImportError:
        pass

    # 3. Resolve relative to this file's directory
    engine_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.py")
    if os.path.isfile(engine_path):
        import importlib.util
        try:
            spec = importlib.util.spec_from_file_location("engine", engine_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {engine_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.GameEngine
        except Exception as e:
            print(f"  Failed to load engine module: {e}")
            sys.exit(1)

    print("  Could not find engine.py. Make sure you're running from the rpg_engine/ directory.")
    sys.exit(1)


GameEngine = _import_game_engine()
from engine import _c


def print_banner():
    """Print the opening banner."""
    banner = r"""
======================================================================

      +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
      |  RPG ENGINE - A Conversational Terminal Adventure            |
      |                                                              |
      |  "Speak freely. The world listens."                          |
      |                                                              |
      +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+

======================================================================
"""
    print(banner)


def main():
    """Main entry point for the RPG engine."""
    print_banner()

    engine = GameEngine()

    # Check for a saved game and present options
    if engine.has_saved_game():
        char_name = engine.state.get("character", {}).get("name", "Unknown")
        if not char_name or char_name.strip() == "":
            char_name = "Unknown"
        print(f"\n  A previous adventure was found.")
        print(f"  Character: {_c('bold', 'cyan', char_name)}")
        print()
        print(f"  {_c('[1]', 'green')} Continue your adventure")
        print(f"  {_c('[2]', 'green')} Start a new adventure")
        print(f"  {_c('[q]', 'green')} Quit")
        print()
        choice = input("  [?] What do you do? " + _c(">", "green") + " ").strip().lower()
        if choice in ("q", "exit", "quit"):
            print("  Your legend remains unwritten... for now.\n")
            return
        if choice == "2":
            # Remove old save before starting new
            save_path = engine._state_path()
            if save_path.exists():
                save_path.unlink()
            engine.state = None
            print("  A new world awaits. Let us begin.\n")
            if not engine.create_character():
                return
        else:
            # Continue existing game
            print("  Loading your adventure...")
            engine.load_game()
            print("  Welcome back, adventurer.\n")
    else:
        print("  A new world awaits. Let us begin.\n")
        # Character creation (only for new games)
        if not engine.create_character():
            return

    # Main game loop
    try:
        engine.game_loop()
    except KeyboardInterrupt:
        print("\n\n  The adventure pauses as you step away...")
        print("  Your journey is saved. Until next time.\n")
        engine.save_game()
    except EOFError:
        print("\n\n  Your words fade into silence...")
        print("  Your journey is saved. Until next time.\n")
        engine.save_game()


if __name__ == "__main__":
    main()
