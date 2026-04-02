"""
Adventure Module Engine
Defines the adventure format and provides scene management.

An adventure is a JSON document describing interconnected scenes with
NPCs, encounters, items, and branching story logic. The AI narrates
from this structured data — it doesn't invent rooms or encounters.

Adventure Structure:
    adventure.json
    ├── metadata (name, author, description, level_range)
    ├── scenes{}
    │   ├── scene_id
    │   │   ├── name, description, ai_notes
    │   │   ├── exits[] (connections to other scenes + conditions)
    │   │   ├── npcs[] (who's here, disposition, dialogue hints)
    │   │   ├── encounters[] (monsters, trigger conditions)
    │   │   ├── items[] (loot, hidden things, DCs to find)
    │   │   ├── events[] (triggered by flags or actions)
    │   │   └── on_enter (script that runs when player enters)
    │   └── ...
    ├── npcs{} (full NPC definitions referenced by scenes)
    ├── global_events[] (events that can trigger anywhere)
    └── starting_scene (where the adventure begins)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AdventureItem:
    """An item that can be found in a scene."""
    name: str
    description: str
    srd_index: str = ""          # SRD equipment/magic-item index if applicable
    hidden: bool = False
    search_dc: int = 0           # DC to find if hidden (0 = always visible)
    quantity: int = 1
    requires_flag: str = ""      # Only appears if this flag is set
    sets_flag: str = ""          # Set this flag when picked up


@dataclass
class AdventureNPC:
    """An NPC in the adventure."""
    id: str
    name: str
    description: str             # Physical description for the AI
    disposition: str = "neutral" # friendly, neutral, hostile, fearful
    dialogue_hints: list[str] = field(default_factory=list)  # Key topics they can discuss
    knows_about: list[str] = field(default_factory=list)     # Info they can reveal
    quest_giver: bool = False
    merchant: bool = False
    inventory: list[dict] = field(default_factory=list)      # If merchant
    monster_index: str = ""      # SRD monster index if they can fight
    alive: bool = True


@dataclass
class EncounterMonster:
    """A monster in an encounter."""
    srd_index: str               # e.g. "goblin"
    count: int = 1
    name_override: str = ""      # e.g. "Goblin Chieftain" instead of "Goblin"
    hp_override: int = 0         # Override default HP
    extra_equipment: list[str] = field(default_factory=list)


@dataclass
class SceneEncounter:
    """An encounter that can trigger in a scene."""
    id: str
    description: str             # AI reads this for narrative flavor
    monsters: list[EncounterMonster] = field(default_factory=list)
    trigger: str = "on_enter"    # on_enter, on_search, on_flag, manual
    trigger_flag: str = ""       # If trigger is "on_flag", which flag
    once: bool = True            # Only trigger once?
    sets_flag: str = ""          # Flag set when encounter completes
    xp_reward: int = 0
    loot: list[dict] = field(default_factory=list)


@dataclass
class SceneExit:
    """A connection from one scene to another."""
    target_scene: str            # Scene ID to go to
    description: str             # "A wooden door to the north"
    direction: str = ""          # "north", "east", "up", "through the door"
    locked: bool = False
    lock_dc: int = 0             # DC to pick the lock
    key_item: str = ""           # Item that unlocks it
    requires_flag: str = ""      # Only available if flag is set
    hidden: bool = False
    search_dc: int = 0           # DC to find if hidden


@dataclass
class SceneEvent:
    """Something that happens in a scene based on conditions."""
    id: str
    description: str             # What the AI should narrate
    trigger: str                 # "on_enter", "on_flag", "on_item_use"
    trigger_flag: str = ""
    trigger_item: str = ""
    sets_flag: str = ""
    once: bool = True
    narrative: str = ""          # Specific text for the AI to incorporate


@dataclass
class Scene:
    """A single location/room in the adventure."""
    id: str
    name: str
    description: str             # Read to the AI for narration
    ai_notes: str = ""           # Extra context for the AI (mood, tone, secrets)
    scene_type: str = "exploration"  # exploration, social, combat, puzzle, rest
    lighting: str = "normal"     # normal, dim, dark, magical
    exits: list[SceneExit] = field(default_factory=list)
    npcs: list[str] = field(default_factory=list)          # NPC IDs present
    encounters: list[SceneEncounter] = field(default_factory=list)
    items: list[AdventureItem] = field(default_factory=list)
    events: list[SceneEvent] = field(default_factory=list)
    on_enter_flag: str = ""      # Flag set when entering
    rest_allowed: bool = True


@dataclass
class Adventure:
    """A complete adventure module."""
    id: str
    name: str
    description: str
    author: str = ""
    version: str = "1.0"
    level_range: tuple[int, int] = (1, 3)
    starting_scene: str = ""
    scenes: dict[str, Scene] = field(default_factory=dict)
    npcs: dict[str, AdventureNPC] = field(default_factory=dict)
    global_events: list[SceneEvent] = field(default_factory=list)
    intro_narrative: str = ""    # Opening text for the AI


def load_adventure(filepath: str) -> Adventure:
    """Load an adventure from a JSON file."""
    with open(filepath) as f:
        data = json.load(f)

    # Parse NPCs
    npcs = {}
    for npc_id, npc_data in data.get("npcs", {}).items():
        npcs[npc_id] = AdventureNPC(id=npc_id, **npc_data)

    # Parse scenes
    scenes = {}
    for scene_id, scene_data in data.get("scenes", {}).items():
        # Parse exits
        exits = [SceneExit(**e) for e in scene_data.pop("exits", [])]
        # Parse encounters
        encounters = []
        for enc_data in scene_data.pop("encounters", []):
            monsters = [EncounterMonster(**m) for m in enc_data.pop("monsters", [])]
            encounters.append(SceneEncounter(monsters=monsters, **enc_data))
        # Parse items
        items = [AdventureItem(**i) for i in scene_data.pop("items", [])]
        # Parse events
        events = [SceneEvent(**e) for e in scene_data.pop("events", [])]

        scenes[scene_id] = Scene(
            id=scene_id,
            exits=exits,
            encounters=encounters,
            items=items,
            events=events,
            **scene_data,
        )

    # Build adventure
    level_range = tuple(data.get("level_range", [1, 3]))
    adventure = Adventure(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        author=data.get("author", ""),
        version=data.get("version", "1.0"),
        level_range=level_range,
        starting_scene=data.get("starting_scene", ""),
        scenes=scenes,
        npcs=npcs,
        intro_narrative=data.get("intro_narrative", ""),
    )

    return adventure


def get_scene_context(adventure: Adventure, scene_id: str, flags: dict) -> dict:
    """
    Build the context packet that gets sent to the AI for a given scene.
    Filters out hidden/conditional content based on current flags.
    """
    scene = adventure.scenes.get(scene_id)
    if not scene:
        return {"error": f"Scene '{scene_id}' not found"}

    # Filter exits by flags
    available_exits = []
    for exit in scene.exits:
        if exit.requires_flag and not flags.get(exit.requires_flag):
            continue
        if exit.hidden:
            continue  # Hidden exits only revealed by searching
        available_exits.append({
            "direction": exit.direction,
            "description": exit.description,
            "target": exit.target_scene,
            "locked": exit.locked,
        })

    # Filter NPCs — only living ones present in this scene
    present_npcs = []
    for npc_id in scene.npcs:
        npc = adventure.npcs.get(npc_id)
        if npc and npc.alive:
            present_npcs.append({
                "name": npc.name,
                "description": npc.description,
                "disposition": npc.disposition,
                "dialogue_hints": npc.dialogue_hints,
            })

    # Filter items by flags (and exclude hidden ones from description)
    visible_items = []
    for item in scene.items:
        if item.requires_flag and not flags.get(item.requires_flag):
            continue
        if item.hidden:
            continue
        visible_items.append({
            "name": item.name,
            "description": item.description,
            "quantity": item.quantity,
        })

    # Pending encounters (untriggered)
    pending_encounters = []
    for enc in scene.encounters:
        flag_key = f"encounter_{enc.id}_complete"
        if enc.once and flags.get(flag_key):
            continue
        if enc.trigger == "on_flag" and not flags.get(enc.trigger_flag):
            continue
        if enc.trigger == "on_enter":
            pending_encounters.append({
                "id": enc.id,
                "description": enc.description,
                "trigger": enc.trigger,
            })

    # Events
    active_events = []
    for event in scene.events:
        flag_key = f"event_{event.id}_done"
        if event.once and flags.get(flag_key):
            continue
        if event.trigger == "on_flag" and not flags.get(event.trigger_flag):
            continue
        if event.trigger == "on_enter":
            active_events.append({
                "id": event.id,
                "description": event.description,
                "narrative": event.narrative,
            })

    return {
        "scene_id": scene.id,
        "name": scene.name,
        "description": scene.description,
        "ai_notes": scene.ai_notes,
        "scene_type": scene.scene_type,
        "lighting": scene.lighting,
        "exits": available_exits,
        "npcs": present_npcs,
        "items": visible_items,
        "pending_encounters": pending_encounters,
        "active_events": active_events,
        "rest_allowed": scene.rest_allowed,
    }


def check_search_results(adventure: Adventure, scene_id: str, flags: dict, roll_total: int) -> list[dict]:
    """
    When a player searches a scene, check what they find based on their roll.
    Returns list of discovered things (hidden exits, hidden items).
    """
    scene = adventure.scenes.get(scene_id)
    if not scene:
        return []

    found = []

    # Hidden items
    for item in scene.items:
        if item.requires_flag and not flags.get(item.requires_flag):
            continue
        if item.hidden and roll_total >= item.search_dc:
            found.append({
                "type": "item",
                "name": item.name,
                "description": item.description,
                "dc": item.search_dc,
            })

    # Hidden exits
    for exit in scene.exits:
        if exit.hidden and roll_total >= exit.search_dc:
            found.append({
                "type": "exit",
                "direction": exit.direction,
                "description": exit.description,
                "dc": exit.search_dc,
            })

    # Search-triggered encounters
    for enc in scene.encounters:
        flag_key = f"encounter_{enc.id}_complete"
        if enc.once and flags.get(flag_key):
            continue
        if enc.trigger == "on_search":
            found.append({
                "type": "encounter",
                "id": enc.id,
                "description": enc.description,
            })

    return found
