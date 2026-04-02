"""Combat management tools."""

import json

from src.mcp.server import mcp, ensure_db
from src.engine.game_session import GameEngine


@mcp.tool()
def start_combat(session_id: int, encounter_id: str) -> str:
    """Start a combat encounter. Call this when game_action returns combat_started=true.
    Spawns monsters, rolls initiative for everyone, and returns the battle setup.

    Args:
        session_id: The active session ID
        encounter_id: The encounter ID from the scene's pending encounters
    """
    ensure_db()
    engine = GameEngine(session_id)

    if not engine.session:
        return f"Error: Session {session_id} not found."

    result = engine.start_combat(encounter_id)

    if "error" in result:
        return f"Error: {result['error']}"

    # Format combat start info
    lines = [
        f"⚔ **COMBAT BEGINS!**",
        f"Encounter: {result['encounter_id']}",
        f"Description: {result['description']}",
        "",
        "**Monsters:**",
    ]
    for m in result["monsters_spawned"]:
        lines.append(f"  {m['name']} — HP: {m['hp']}, AC: {m['ac']}, Initiative: {m['initiative']}")

    lines.append(f"\nPlayer Initiative: {result['player_initiative']}")
    lines.append("\n**Initiative Order:**")
    for i, combatant in enumerate(result["initiative_order"], 1):
        marker = " ← PLAYER" if combatant.get("is_player") else ""
        lines.append(f"  {i}. {combatant['name']} (Initiative: {combatant['initiative']}){marker}")

    lines.append("\nCombat is active! The player can now attack, cast spells, or take other combat actions.")
    return "\n".join(lines)


@mcp.tool()
def get_combat_state(session_id: int) -> str:
    """Check the current state of combat — initiative order, enemy HP, player HP.
    Use this if you need to remind yourself of the battlefield situation.

    Args:
        session_id: The active session ID
    """
    ensure_db()
    engine = GameEngine(session_id)

    if not engine.session:
        return f"Error: Session {session_id} not found."

    if not engine.session.in_combat:
        return "Not currently in combat."

    entities = engine.get_combat_entities()
    character = engine.get_character()
    initiative = json.loads(engine.session.initiative_order or "[]")

    lines = ["**Combat State:**", ""]

    lines.append("**Initiative Order:**")
    for i, combatant in enumerate(initiative, 1):
        marker = " ← PLAYER" if combatant.get("is_player") else ""
        lines.append(f"  {i}. {combatant['name']} (Initiative: {combatant['initiative']}){marker}")

    lines.append("\n**Enemies:**")
    for e in entities:
        status = "ALIVE" if e.is_alive else "DEAD"
        lines.append(f"  {e.name}: {e.current_hp}/{e.max_hp} HP, AC {e.armor_class} [{status}]")

    if character:
        lines.append(f"\n**Player:** {character.name} — {character.current_hp}/{character.max_hp} HP, AC {character.armor_class}")

    return "\n".join(lines)
