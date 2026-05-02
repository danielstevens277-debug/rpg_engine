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

def _import_game_engine_module():
    """Import engine module, supporting both 'python main.py' and 'python rpg_engine/main.py'."""
    # 1. Try bare import (works when run from inside rpg_engine/)
    try:
        import engine
        return engine
    except ImportError:
        pass

    # 2. Try package import (works when rpg_engine/ is on the path)
    try:
        import rpg_engine.engine as engine
        return engine
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
            return mod
        except Exception as e:
            print(f"  Failed to load engine module: {e}")
            sys.exit(1)

    print("  Could not find engine.py. Make sure you're running from the rpg_engine/ directory.")
    sys.exit(1)


engine_mod = _import_game_engine_module()
GameEngine = engine_mod.GameEngine
_c = engine_mod._c
_state_path = engine_mod._state_path


def _import_autoplay():
    """Import autoplay module, supporting both python main.py and python rpg_engine/main.py."""
    try:
        import autoplay
        return autoplay
    except ImportError:
        pass
    try:
        import rpg_engine.autoplay as autoplay
        return autoplay
    except ImportError:
        pass
    autoplay_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoplay.py")
    if os.path.isfile(autoplay_path):
        import importlib.util
        try:
            spec = importlib.util.spec_from_file_location("autoplay", autoplay_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {autoplay_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except Exception as e:
            print(f"  Failed to load autoplay module: {e}")
            sys.exit(1)
    print("  Could not find autoplay.py. Make sure you're running from the rpg_engine/ directory.")
    sys.exit(1)


def _launch_autoplay(engine):
    """Launch autoplay mode with the given engine state."""
    autoplay = _import_autoplay()
    autoplay.autoplay_game_loop(engine, max_turns=50, sandbox=True)


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
        print(f"  Character: {_c(char_name, 'cyan', 'bold')}")
        print()
        print(f"  {_c('[1]', 'green')} Continue your adventure")
        print(f"  {_c('[2]', 'green')} Start a new adventure")
        print(f"  {_c('[3]', 'green')} Watch an adventure unfold (autoplay)")
        print(f"  {_c('[4]', 'green')} Start a fresh auto-play adventure")
        print(f"  {_c('[q]', 'green')} Quit")
        print()
        choice = input("  [?] What do you do? " + _c(">", "green") + " ").strip().lower()
        if choice in ("q", "exit", "quit"):
            print("  Your legend remains unwritten... for now.\n")
            return
        if choice == "1":
            # Continue existing game
            print("  Loading your adventure...")
            engine.load_game()
            print("  Welcome back, adventurer.\n")
        elif choice == "2":
            # Remove old save before starting new
            save_path = _state_path()
            if save_path.exists():
                save_path.unlink()
            engine.state = None
            print("  A new world awaits. Let us begin.\n")
            if not engine.create_character():
                return
        elif choice == "3":
            # Watch an adventure unfold (autoplay with existing save)
            print("  Loading your adventure...")
            engine.load_game()
            print("  The Oracle takes the reins...\n")
            _launch_autoplay(engine)
            return
        elif choice == "4":
            # Start a fresh auto-play adventure (no save)
            save_path = _state_path()
            if save_path.exists():
                save_path.unlink()
            engine.state = None
            print("  The Oracle prepares to play both sides...\n")
            _launch_autoplay(engine)
            return
        else:
            # Default: continue existing game
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
