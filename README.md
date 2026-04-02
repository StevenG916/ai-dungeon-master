# AI Dungeon Master

A solo D&D 5th Edition adventure engine with AI-powered narration. Built on the 5e SRD (System Reference Document) under the OGL/CC-BY-4.0 license.

The game engine handles all mechanics (dice rolls, combat, character sheets, skill checks) deterministically — the AI only narrates the story. Adventures are defined as structured JSON modules, so the AI can't hallucinate rooms, items, or encounters.

## Quick Start

```bash
# Clone the repo
git clone <your-repo-url>
cd ai-dungeon-master

# Install dependencies
pip install -r requirements.txt

# Initialize the database (loads 2,278 SRD entries)
# This happens automatically on first server start

# Optional: Set your Anthropic API key for AI narration
# Without it, the game runs in mock narrative mode
export ANTHROPIC_API_KEY=sk-ant-...

# Run the server
PYTHONPATH=. python src/api/main.py
```

Then open `http://localhost:8000` in your browser.

## How to Play

1. **Create a Character** — Choose race, class, roll ability scores, pick skills
2. **Choose an Adventure** — Select from available adventure modules
3. **Play** — Type commands or click buttons to explore, talk to NPCs, fight monsters

### Commands
- `go north` / `move outside` — Move to a different area
- `talk to Bram about goblins` — Talk to NPCs
- `attack goblin` — Attack in combat
- `search` / `investigate` — Search for hidden items/passages
- `look around` — Examine your surroundings
- `rest` / `long rest` — Rest to recover HP
- Or type anything else as a free action for the AI to interpret

## Architecture

```
src/
├── api/main.py              # FastAPI routes (22 endpoints)
├── data/srd_loader.py       # Loads 5e SRD JSON → SQLite
├── engine/
│   ├── dice.py              # d20 rolls, advantage, crits, ability checks
│   ├── character_creation.py # Race/class/skills/equipment from SRD
│   ├── adventure.py         # Adventure module loader & scene context
│   ├── game_session.py      # Core state machine & combat
│   └── narrator.py          # Claude API integration for narration
├── models/database.py       # SQLAlchemy models
adventures/                  # JSON adventure modules
5e-database/                 # Cloned 5e SRD data repo
```

**Key Design Principle:** The engine resolves all mechanics. The AI only narrates results it's given. This prevents hallucination of game state.

## Adventure Modules

Adventures are JSON files in the `adventures/` directory. See `adventures/goblin_cave.json` for the format. Key elements:

- **Scenes** — Rooms/locations with descriptions, exits, NPCs, encounters
- **NPCs** — Characters with dialogue hints, dispositions, knowledge
- **Encounters** — Monster groups with SRD stat blocks, trigger conditions, XP/loot
- **Story Flags** — Boolean flags that track player progress and gate content
- **Items** — Loot with optional hide DCs and flag requirements

## SRD Data

Uses the [5e-bits/5e-database](https://github.com/5e-bits/5e-database) repository:
- 334 monsters with full stat blocks
- 319 spells
- 12 classes with features and levels
- 9 races with subraces
- 237 equipment items
- 362 magic items

All data is OGL/CC-BY-4.0 licensed.

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, SQLite (WAL mode)
- **Frontend:** Vanilla JS, CSS
- **AI:** Anthropic Claude API (optional — runs in mock mode without key)
- **Data:** 5e SRD via 5e-database repo

## License

Code is MIT licensed. Game content from the SRD is under the Open Game License v1.0a and/or Creative Commons CC-BY-4.0.
