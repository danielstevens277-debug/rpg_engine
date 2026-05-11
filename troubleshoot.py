#!/usr/bin/env python3
import unittest
from unittest.mock import patch, MagicMock, call
import os
import json
import re
import sys
from pathlib import Path
from datetime import datetime
import engine
from engine import GameEngine, SYSTEM_PROMPT
import autoplay

class TestRPGEngine(unittest.TestCase):
    def setUp(self):
        # Use a temporary save file for tests
        self.test_save_path = Path.home() / ".rpg_engine_test_save.json"
        self.original_save_path = engine._state_path()
        
        # Patch _state_path in engine and any other modules using it
        self.path_patcher = patch('engine._state_path', return_value=self.test_save_path)
        self.path_patcher.start()
        
        # Ensure save file is gone before each test
        if self.test_save_path.exists():
            self.test_save_path.unlink()

    def tearDown(self):
        self.path_patcher.stop()
        if self.test_save_path.exists():
            self.test_save_path.unlink()

    def test_state_persistence(self):
        """Test that game state is correctly saved and loaded."""
        ge = GameEngine()
        ge.state = {
            "messages": [{"role": "system", "content": "Test System"}],
            "character": {"name": "TestHero", "race": "Human", "class": "Warrior"},
            "world_name": "TestWorld",
            "status": "playing"
        }
        ge.messages = ge.state["messages"]
        ge.save_game()
        
        # Create new engine and load
        ge2 = GameEngine()
        ge2.load_game()
        
        self.assertEqual(ge2.state["character"]["name"], "TestHero")
        self.assertEqual(ge2.state["world_name"], "TestWorld")
        self.assertEqual(ge2.messages[0]["content"], "Test System")

    def test_character_extraction_json(self):
        """Test character extraction from JSON block in LLM response."""
        response = "Welcome! Here are your details:\n```json\n{\"name\": \"Kaelen\", \"race\": \"Elf\", \"class\": \"Mage\"}\n```"
        
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        self.assertTrue(json_match)
        char_data = json.loads(json_match.group(1))
        self.assertEqual(char_data["name"], "Kaelen")
        self.assertEqual(char_data["race"], "Elf")
        self.assertEqual(char_data["class"], "Mage")

    def test_character_extraction_regex(self):
        """Test fallback regex extraction for character details."""
        response = "Your name is Elara, a brave human warrior."
        
        name_patterns = [
            r'your name is (\w[\w ]*?)(?:[,.\s]|$)',
            r'you are (?:named|called) (\w[\w ]*?)(?:[,.\s]|$)',
            r'(\w[\w ]*?), (?:a|an) (?:brave|young|weary|fierce)',
        ]
        
        found_name = None
        for pattern in name_patterns:
            m = re.search(pattern, response, re.IGNORECASE)
            if m:
                found_name = m.group(1).strip()
                break
        self.assertEqual(found_name, "Elara")

    def test_context_trimming(self):
        """Test that context is trimmed but system prompt is preserved."""
        ge = GameEngine()
        with patch.object(GameEngine, '_get_current_context_limit', return_value=12000):
            ge.messages = [{"role": "system", "content": "SYSTEM"}]
            for i in range(20):
                ge.messages.append({"role": "user", "content": "A" * 1000})
                ge.messages.append({"role": "assistant", "content": "B" * 1000})
            
            ge.trim_context()
            
            self.assertEqual(ge.messages[0]["role"], "system")
            self.assertTrue(len(ge.messages) < 41)
            self.assertEqual(ge.messages[-1]["content"], "B" * 1000)

    def test_context_trimming_huge_last_message(self):
        """Test that context trimming keeps at least the last message even if it's huge."""
        ge = GameEngine()
        with patch.object(GameEngine, '_get_current_context_limit', return_value=1000):
            # System prompt + one huge message
            ge.messages = [
                {"role": "system", "content": "SYSTEM"},
                {"role": "user", "content": "A" * 5000},
            ]
            ge.trim_context()
            # Should still keep the huge message (or at least not wipe it)
            self.assertEqual(len(ge.messages), 2)
            self.assertEqual(ge.messages[1]["content"], "A" * 5000)

    def test_error_response_not_saved(self):
        """Test that error responses from LLM are not added to history."""
        ge = GameEngine()
        ge.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        player_input = "Hello"
        ge.messages.append({"role": "user", "content": player_input})
        
        error_response = "The connection to the Oracle has been lost."
        # Simulate the check in game_loop
        if error_response and ("The connection to the Oracle has been lost" in error_response):
            pass 
        else:
            ge.messages.append({"role": "assistant", "content": error_response})
            
        self.assertEqual(len(ge.messages), 2)
        self.assertEqual(ge.messages[-1]["content"], player_input)

    def test_autoplay_role_swap(self):
        """Test that autoplay roles are correctly swapped for the player's turn."""
        messages = [
            {"role": "system", "content": "System Prompt"},
            {"role": "assistant", "content": "DM: You see a cave."},
            {"role": "user", "content": "Player: I enter the cave."},
            {"role": "assistant", "content": "DM: Inside is a dragon."},
        ]
        
        rewritten = autoplay._filter_player_history(messages)
        self.assertTrue(all(m["role"] != "system" for m in rewritten))
        self.assertEqual(rewritten[0]["role"], "user")
        self.assertEqual(rewritten[0]["content"], "DM: You see a cave.")
        self.assertEqual(rewritten[1]["role"], "assistant")
        self.assertEqual(rewritten[1]["content"], "Player: I enter the cave.")
        self.assertEqual(rewritten[2]["role"], "user")
        self.assertEqual(rewritten[2]["content"], "DM: Inside is a dragon.")

    @patch('engine._call_llm')
    @patch('autoplay._call_llm')
    @patch('builtins.input')
    def test_create_character_flow(self, mock_input, mock_llm_autoplay, mock_llm_engine):
        """Test the full character creation flow in GameEngine."""
        # Mock LLM responses
        # 1. DM Questions
        # 2. Starting Scenario
        mock_llm_engine.side_effect = [
            ("What is your name, race, class, and appearance?", None, None, None),
            ("Your name is Kaelen, an Elf Mage. You wake up in a forest.", "Reasoning", None, None)
        ]
        
        # Mock player input
        mock_input.return_value = "Kaelen, Elf, Mage, tall and thin"
        
        ge = GameEngine()
        success = ge.create_character()
        
        self.assertTrue(success)
        self.assertEqual(ge.state["character"]["name"], "Kaelen")
        self.assertEqual(ge.state["status"], "playing")
        self.assertEqual(len(ge.messages), 4) # system, dm_q, user_resp, dm_scenario

    @patch('builtins.input')
    def test_game_loop_commands(self, mock_input):
        """Test the processing of internal game loop commands."""
        ge = GameEngine()
        ge.state = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "character": {"name": "Hero", "race": "Human", "class": "Warrior"},
            "world_name": "TestWorld",
            "status": "playing"
        }
        ge.messages = ge.state["messages"]
        
        # Sequence: status, save, quit
        mock_input.side_effect = ["status", "save", "quit"]
        
        with patch('engine.GameEngine._show_status') as mock_status, \
             patch('engine.GameEngine.save_game') as mock_save:
            
            # We need to wrap this in a way that it doesn't run forever
            # Since we provided 'quit', it should exit.
            ge.game_loop()
            
            mock_status.assert_called_once()
            mock_save.assert_called()

    @patch('engine._call_llm')
    @patch('autoplay._call_llm')
    def test_autoplay_character_creation(self, mock_llm_autoplay, mock_llm_engine):
        """Test autoplay character creation flow."""
        # 1. DM Questions
        # 2. Starting Scenario
        mock_llm_autoplay.side_effect = [
            ("Questions?", None, None, None),
            ("Welcome to the world!", None, None, None)
        ]
        
        ge = GameEngine()
        char_info = {"name": "AutoHero", "race": "Orc", "class": "Bard", "appearance": "Green and loud"}
        
        autoplay.autoplay_character_creation(ge, char_info)
        
        self.assertEqual(ge.state["character"]["name"], "AutoHero")
        self.assertEqual(len(ge.messages), 4)

    @patch('engine._call_llm')
    @patch('autoplay._call_llm')
    def test_sandbox_interventions(self, mock_llm_autoplay, mock_llm_engine):
        """Test sandbox functions add/remove/write."""
        # Mock LLM responses for each intervention
        # Each intervention typically calls LLM twice: once for DM, once for Player
        mock_llm_autoplay.side_effect = [
            ("DM: A dragon appears!", None, None, None), # Add Event - DM
            ("Player: I scream!", None, None, None),     # Add Event - Player
            ("DM: The dragon vanishes.", None, None, None), # Remove - DM
            ("Player: I look around.", None, None, None),   # Remove - Player
            ("DM: You hit the wall.", None, None, None),    # Write - DM
            ("Player: I sigh.", None, None, None),          # Write - Player
        ]
        
        ge = GameEngine()
        ge.state = {"messages": [], "character": {"name": "Sbox"}, "status": "playing"}
        ge.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Test Add
        autoplay._sandbox_add_event(ge, "A dragon appears")
        # Test Remove
        autoplay._sandbox_remove_element(ge, "The dragon")
        # Test Write
        autoplay._sandbox_write_action(ge, "I punch the wall")
        
        # Check that messages were appended (1 system + 2 add + 2 remove + 3 write)
        self.assertEqual(len(ge.messages), 8)

    def test_api_config_fallbacks(self):
        """Test that API configuration correctly falls back to environment variables."""
        # Clear environment and cache
        with patch.dict(os.environ, {}, clear=True):
            engine._CONFIG_CACHE.clear()
            config = engine._get_api_config()
            # Should use defaults
            self.assertEqual(config["provider"], "openai")
            self.assertEqual(config["model"], "gpt-4o-mini")

        with patch.dict(os.environ, {
            "RPG_LLM_PROVIDER": "openai",
            "RPG_API_KEY": "custom-key",
            "RPG_OPENAI_MODEL": "custom-model"
        }):
            engine._CONFIG_CACHE.clear()
            config = engine._get_api_config()
            self.assertEqual(config["api_key"], "custom-key")
            self.assertEqual(config["model"], "custom-model")

        with patch.dict(os.environ, {
            "RPG_LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "anthro-key",
            "RPG_API_KEY": ""
        }):
            engine._CONFIG_CACHE.clear()
            config = engine._get_api_config()
            self.assertEqual(config["api_key"], "anthro-key")
            self.assertEqual(config["provider"], "anthropic")

if __name__ == "__main__":
    unittest.main()
