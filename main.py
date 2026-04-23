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
        spec = importlib.util.spec_from_file_location("engine", engine_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.GameEngine

    print("  Could not find engine.py. Make sure you're running from the rpg_engine/ directory.")
    sys.exit(1)


GameEngine = _import_game_engine()


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

    # Check for a saved game
    if engine.has_saved_game():
        print("\n  A previous adventure was found. Loading...")
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
