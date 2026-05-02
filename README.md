# 🐉 Conversational Terminal RPG Engine

A pure natural-language, terminal-based RPG where an LLM acts as a system-agnostic Dungeon Master. All game mechanics — dice rolls, attribute checks, combat initiative, inventory, health — are handled invisibly by the LLM. The player navigates the world entirely through natural language questions and actions. **No menus. No buttons. No choices. Just your imagination.**

## Features

- **Pure natural-language interaction** — describe actions, ask questions, talk to NPCs, examine objects. Everything is freeform.
- **System-agnostic DM** — the LLM handles all mechanics behind the scenes. No dice, no numbers, no game notation visible to the player.
- **Auto-Play mode** — watch the LLM play both the Dungeon Master and the player character, generating a self-directed story.
- **Persistent character state** — your character, world state, and full conversation history are saved to a JSON file. Pick up where you left off.
- **Character creation** — describe your character in natural language. The LLM interprets your description and weaves it into the world.
- **OpenAI-compatible API** — works with any OpenAI-compatible endpoint (OpenAI, local models via Ollama/LM Studio, etc.). Also supports Anthropic Claude.
- **Pure terminal UI** — no dependencies on GUI frameworks. Just your terminal and your imagination.

## Installation

### Prerequisites

- Python 3.9+
- An OpenAI API key (or any OpenAI-compatible endpoint)

### Setup

```bash
cd rpg_engine
pip install -r requirements.txt
```

### Configure your API key

Set the `OPENAI_API_KEY` environment variable (or use the custom `RPG_API_KEY`):

```bash
# For OpenAI
export OPENAI_API_KEY="sk-your-key-here"

# Or use the RPG-specific variable
export RPG_API_KEY="sk-your-key-here"
```

### Run

#### Interactive Mode (Human Plays)

```bash
python main.py
```

#### Auto-Play Mode (LLM Plays Both Roles)

```bash
python autoplay.py              # Continue from saved game
python autoplay.py --new        # Start a fresh auto-play game
python autoplay.py --turns 20   # Limit to 20 DM-player turns
python autoplay.py --new --turns 20 --char-choice  # New game with character choice
```

**Auto-Play Modes:**
- `--new` — Start a fresh game instead of continuing from a save
- `--turns N` — Maximum number of DM-player turn pairs (default: 50)
- `--char-choice` — Choose between AI-generated character or manual description at startup

In auto-play mode, the LLM alternates between the **Dungeon Master** (narrating the world) and the **Player Character** (deciding what to do next), generating a self-directed story with streaming output, thinking blocks, and styled narrative presentation.

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `RPG_LLM_PROVIDER` | `openai` | `openai` or `anthropic` |
| `RPG_API_KEY` | _(empty)_ | Primary API key (checked first) |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key (fallback) |
| `RPG_BASE_URL` | _(empty)_ | Custom API base URL (for local models) |
| `OPENAI_BASE_URL` | _(empty)_ | OpenAI-compatible base URL |
| `RPG_MODEL` | _(empty)_ | Model name (uses provider default) |
| `RPG_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |

### Local models (Ollama, LM Studio, etc.)

```bash
# Ollama (running locally on port 11434)
export RPG_API_KEY="not-needed"
export RPG_BASE_URL="http://localhost:11434/v1"
export RPG_OPENAI_MODEL="llama3"

python main.py
```

```bash
# LM Studio (default port 1234)
export RPG_API_KEY="lm-studio"
export RPG_BASE_URL="http://localhost:1234/v1"
export RPG_OPENAI_MODEL="lmstudio-community/llama-3-8b-instruct"

python main.py
```

## How It Works

### Architecture

#### Interactive Mode (Human Plays)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Terminal   │────▶│   Engine     │────▶│     LLM      │
│   (player)   │◀────│   (Python)   │◀────│   (GPT-4 etc)│
│              │     │              │     │              │
│  Natural     │     │  JSON        │     │  Narrative   │
│  language    │     │  persistence │     │  responses   │
│  input       │     │  State mgmt  │     │  (no mechanics│
│              │     │  Game loop   │     │   visible)    │
└──────────────┘     └──────────────┘     └──────────────┘
```

#### Auto-Play Mode (LLM Plays Both Roles)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Terminal   │◀────│   Engine     │◀────│     LLM      │
│   (observer) │     │   (Python)   │     │   (GPT-4 etc)│
│              │     │              │     │              │
│  Styled      │     │  JSON        │     │  DM role ────▶│
│  narrative   │     │  persistence │     │  Player role ─▶│
│  output      │     │  State mgmt  │     │  (dual roles) │
│              │     │  Game loop   │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Game Flow

1. **Initialization** — The engine checks for a saved game (JSON file at `~/.rpg_engine_save.json`). If found, it loads the conversation history and character state.

2. **Character Creation** — The LLM asks the player about their character (name, race, class, appearance) in a warm, storytelling style. The player responds in natural language.

3. **Game Loop** — The player types anything they want to do. The engine sends the full conversation history to the LLM, which responds with narrative. The engine saves the state after each turn.

4. **Persistence** — After every turn, the entire conversation history and character state are saved to `~/.rpg_engine_save.json`. The game can be resumed at any time.

### System Prompt

The LLM receives a comprehensive system prompt that instructs it to:

- Act as a system-agnostic Dungeon Master
- Handle ALL mechanics invisibly (dice rolls, checks, combat, inventory, health)
- Never expose mechanical notation to the player
- Respond in vivid narrative prose
- Maintain world consistency and track state internally
- Never break character or mention being an AI
- End each response with an open invitation for the player to continue

### State File

The game state is stored as JSON at `~/.rpg_engine_save.json`:

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "I want to enter the tavern..."},
    {"role": "assistant", "content": "The tavern door creaks open..."}
  ],
  "character": {
    "name": "Aldric",
    "race": "Human",
    "class": "Rogue"
  },
  "world_name": "the Known Realm",
  "status": "playing",
  "_saved_at": "2025-01-15T14:30:00"
}
```

## Commands (Interactive Mode)

| Input | Action |
|---|---|
| _(anything else)_ | Roleplay — describe actions, ask questions, talk to NPCs |
| `quit` / `exit` / `q` | Save and exit |
| `save` | Manually save the current game |
| `status` | Show character and game status |
| `help` | Show available commands |

## Auto-Play Mode

Auto-play mode lets the LLM play both the Dungeon Master and the player character, generating a self-directed story. Each role gets its own thinking block and output block, with the player character styled in green and the DM in cyan.

**How it works:**
1. **Character Creation** — Either AI-generates a character or you describe one
2. **Starting Scenario** — The DM generates an opening scene based on the character
3. **Game Loop** — The DM narrates, then the player character decides what to do, repeating
4. **Persistence** — The game saves after each complete turn (DM + player pair)

**Visual presentation:**
- 🟢 Green blocks — Player character actions and dialogue
- 🔵 Cyan blocks — Dungeon Master narrative
- ⚫ Dim blocks — Thinking/reasoning content
- 🟡 Turn counter — Shows progress through the turn limit

## Commands (Auto-Play)

| Argument | Action |
|---|---|
| _(no args)_ | Continue from saved game |
| `--new` | Start a fresh game |
| `--turns N` | Limit to N DM-player turn pairs (default: 50) |
| `--char-choice` | Choose character creation mode at startup |
| `--help` | Show help message |

## Design Philosophy

This engine embodies a single principle: **the player's imagination is the only interface.**

- No menus to navigate
- No buttons to click
- No numbered choices to pick from
- No mechanical overhead — the LLM handles all of that invisibly

The player simply types what they want to do, and the LLM (as Dungeon Master) responds with narrative. The Python engine's only job is to persist state and manage the LLM conversation.

This creates a truly immersive experience where the boundary between game and story dissolves. The player isn't "playing a game" — they're telling a story with a partner who knows all the rules but never mentions them.

## Requirements

- Python 3.9+
- `openai` package (for OpenAI API)
- `anthropic` package (optional, for Claude support)
- An API key for your chosen LLM provider

## License

MIT
