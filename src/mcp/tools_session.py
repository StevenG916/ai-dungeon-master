"""Session and adventure management tools."""

import glob
import json

from src.mcp.server import mcp, ensure_db
from src.engine.adventure import load_adventure
from src.engine.game_session import GameEngine, create_game_session
from src.models.database import GameSession, SessionParticipant, get_session

DB_PATH = "game.db"


@mcp.tool()
def list_adventures() -> str:
    """List all available adventure modules that can be played.
    Shows the adventure name, description, and recommended level range."""
    ensure_db()
    adventures = []
    for filepath in glob.glob("adventures/*.json"):
        try:
            adv = load_adventure(filepath)
            adventures.append(
                f"**{adv.name}** (ID: {adv.id})\n"
                f"  {adv.description}\n"
                f"  Level Range: {adv.level_range[0]}-{adv.level_range[1]}\n"
                f"  File: {filepath}"
            )
        except Exception as e:
            adventures.append(f"Error loading {filepath}: {e}")

    if not adventures:
        return "No adventure modules found in the adventures/ directory."
    return "\n\n".join(adventures)


@mcp.tool()
def start_session(character_id: int, adventure_id: str) -> str:
    """Start a new game session with a character and adventure.
    Returns the adventure intro narrative and the first scene description.

    Args:
        character_id: The ID of the character to play (from list_characters)
        adventure_id: The adventure file path (from list_adventures), e.g. "adventures/goblin_cave.json"
    """
    ensure_db()

    # Resolve adventure ID — accept file path or slug
    adventure_file = adventure_id
    if not adventure_file.endswith(".json"):
        # Try to find the adventure by slug
        for filepath in glob.glob("adventures/*.json"):
            try:
                adv = load_adventure(filepath)
                if adv.id == adventure_id:
                    adventure_file = filepath
                    break
            except Exception:
                pass
        else:
            # Try common patterns
            for pattern in [
                f"adventures/{adventure_id}.json",
                f"adventures/{adventure_id.replace('-v1', '')}.json",
            ]:
                matches = glob.glob(pattern)
                if matches:
                    adventure_file = matches[0]
                    break

    # Create the session
    session = create_game_session(
        character_id=character_id,
        adventure_file=adventure_file,
    )

    # Load the engine to get full context
    engine = GameEngine(session.id)
    scene_ctx = engine.get_current_scene_context()
    adventure = engine.adventure

    # Log the session start
    engine.log_system(f"Adventure started: {adventure.name}")

    # Build the opening
    intro = adventure.intro_narrative if adventure else "Your adventure begins..."
    scene_desc = scene_ctx.get("description", "You find yourself in an unknown place.")
    scene_name = scene_ctx.get("name", "Unknown")

    npcs = scene_ctx.get("npcs", [])
    npc_text = ""
    if npcs:
        npc_names = [f"{n['name']} ({n['disposition']})" for n in npcs]
        npc_text = f"\n\n**NPCs present:** {', '.join(npc_names)}"

    exits = scene_ctx.get("exits", [])
    exit_text = ""
    if exits:
        exit_descs = [f"{e['direction']}: {e['description']}" for e in exits]
        exit_text = f"\n\n**Exits:** {'; '.join(exit_descs)}"

    return (
        f"**Session started!** (Session ID: {session.id})\n\n"
        f"---\n\n"
        f"**{adventure.name}**\n\n"
        f"{intro}\n\n"
        f"---\n\n"
        f"**{scene_name}**\n\n"
        f"{scene_desc}"
        f"{npc_text}"
        f"{exit_text}"
    )


@mcp.tool()
def get_session_state(session_id: int) -> str:
    """Get the full current state of a game session.
    Returns scene info, character state, combat status, and story progress.

    Args:
        session_id: The session ID to check
    """
    ensure_db()
    engine = GameEngine(session_id)

    if not engine.session:
        return f"Session {session_id} not found."

    context = engine.build_ai_context()
    scene = context.get("scene", {})
    character = context.get("character", {})

    lines = [f"**Session {session_id}** — {engine.adventure.name if engine.adventure else 'Unknown'}"]
    lines.append(f"State: {engine.session.state}")

    # Scene
    lines.append(f"\n**Current Scene: {scene.get('name', 'Unknown')}**")
    lines.append(scene.get("description", ""))
    if scene.get("ai_notes"):
        lines.append(f"DM Notes: {scene['ai_notes']}")

    # NPCs
    npcs = scene.get("npcs", [])
    if npcs:
        lines.append(f"\nNPCs: {', '.join(n['name'] + ' (' + n['disposition'] + ')' for n in npcs)}")

    # Exits
    exits = scene.get("exits", [])
    if exits:
        lines.append(f"Exits: {', '.join(e['direction'] + ' → ' + e.get('description', '') for e in exits)}")

    # Items
    items = scene.get("items", [])
    if items:
        lines.append(f"Visible items: {', '.join(i['name'] for i in items)}")

    # All encounters (including manual ones the DM needs to trigger)
    if engine.adventure:
        adventure_scene = engine.adventure.scenes.get(engine.session.current_scene_id)
        if adventure_scene:
            flags = engine.get_flags()
            available_encounters = []
            for enc in adventure_scene.encounters:
                flag_key = f"encounter_{enc.id}_complete"
                if enc.once and flags.get(flag_key):
                    continue
                trigger_note = f"[{enc.trigger}]"
                if enc.trigger == "manual":
                    trigger_note = "[manual — start when narratively appropriate]"
                elif enc.trigger == "on_flag":
                    active = "ACTIVE" if flags.get(enc.trigger_flag) else "waiting for flag: " + enc.trigger_flag
                    trigger_note = f"[on_flag: {active}]"
                available_encounters.append(f"`{enc.id}`: {enc.description} {trigger_note}")
            if available_encounters:
                lines.append(f"\n**Available Encounters:**")
                for e in available_encounters:
                    lines.append(f"  - {e}")
                lines.append("  -> Call `start_combat(session_id, encounter_id)` to begin.")

    # Character
    if character:
        lines.append(f"\n**Character: {character.get('name', '?')}**")
        lines.append(f"  {character.get('race', '?')} {character.get('class', '?')} Level {character.get('level', 1)}")
        lines.append(f"  HP: {character.get('hp', '?')} | AC: {character.get('ac', '?')}")

    # Combat
    if context.get("in_combat"):
        combat = context.get("combat", {})
        lines.append("\n**COMBAT ACTIVE**")
        lines.append(f"Initiative: {json.dumps(combat.get('initiative_order', []))}")
        for enemy in combat.get("enemies", []):
            status = "ALIVE" if enemy["alive"] else "DEAD"
            lines.append(f"  {enemy['name']}: {enemy['hp']} HP, AC {enemy['ac']} [{status}]")

    # Story flags
    flags = context.get("story_flags", {})
    if flags:
        lines.append(f"\nStory flags: {json.dumps(flags)}")

    return "\n".join(lines)


@mcp.tool()
def list_sessions() -> str:
    """List all existing game sessions. Use this to find sessions to resume."""
    ensure_db()
    db = get_session(DB_PATH)
    sessions = db.query(GameSession).all()
    db.close()

    if not sessions:
        return "No game sessions found. Start a new one with start_session."

    lines = []
    for s in sessions:
        lines.append(
            f"**Session {s.id}** — {s.name}\n"
            f"  Adventure: {s.adventure_id} | State: {s.state}\n"
            f"  Scene: {s.current_scene_id} | Combat: {'Yes' if s.in_combat else 'No'}"
        )
    return "\n\n".join(lines)
