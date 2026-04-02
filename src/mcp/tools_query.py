"""Query tools for checking character and narrative state."""

import json

from src.mcp.server import mcp, ensure_db
from src.engine.dice import ability_modifier
from src.models.database import Character, NarrativeLog, get_session

DB_PATH = "game.db"


@mcp.tool()
def get_character_sheet(character_id: int) -> str:
    """Get the full character sheet for a character.
    Shows all stats, equipment, proficiencies, and features.

    Args:
        character_id: The character ID
    """
    ensure_db()
    db = get_session(DB_PATH)
    char = db.query(Character).get(character_id)
    db.close()

    if not char:
        return f"Character {character_id} not found."

    equipment = json.loads(char.equipment)
    skills = json.loads(char.skill_proficiencies)
    saves = json.loads(char.saving_throw_proficiencies)
    proficiencies = json.loads(char.proficiencies)
    languages = json.loads(char.languages)
    spells = json.loads(char.spells_known)
    features = json.loads(char.features)
    traits = json.loads(char.traits)

    equipped = [e["name"] for e in equipment if e.get("equipped")]
    inventory = [f"{e['name']} x{e['quantity']}" for e in equipment if not e.get("equipped")]

    lines = [
        f"# {char.name}",
        f"**{char.race}{' (' + char.subrace + ')' if char.subrace else ''} {char.char_class}** Level {char.level}",
        f"Alignment: {char.alignment} | XP: {char.xp}",
        "",
        f"**HP:** {char.current_hp}/{char.max_hp} | **AC:** {char.armor_class} | **Speed:** {char.speed} ft",
        "",
        "**Ability Scores:**",
        f"  STR: {char.strength} ({ability_modifier(char.strength):+d})",
        f"  DEX: {char.dexterity} ({ability_modifier(char.dexterity):+d})",
        f"  CON: {char.constitution} ({ability_modifier(char.constitution):+d})",
        f"  INT: {char.intelligence} ({ability_modifier(char.intelligence):+d})",
        f"  WIS: {char.wisdom} ({ability_modifier(char.wisdom):+d})",
        f"  CHA: {char.charisma} ({ability_modifier(char.charisma):+d})",
        "",
        f"**Proficiency Bonus:** +{char.get_proficiency_bonus()}",
        f"**Saving Throws:** {', '.join(saves)}",
        f"**Skills:** {', '.join(skills)}",
        f"**Proficiencies:** {', '.join(proficiencies)}",
        f"**Languages:** {', '.join(languages)}",
    ]

    if equipped:
        lines.append(f"\n**Equipped:** {', '.join(equipped)}")
    if inventory:
        lines.append(f"**Inventory:** {', '.join(inventory)}")
    if spells:
        lines.append(f"\n**Spells Known:** {', '.join(spells)}")
    if features:
        lines.append(f"**Features:** {', '.join(features)}")
    if traits:
        lines.append(f"**Racial Traits:** {', '.join(traits)}")

    return "\n".join(lines)


@mcp.tool()
def get_narrative_log(session_id: int, limit: int = 20) -> str:
    """Get recent narrative log entries for a session.
    Use this to recall what happened recently in the story for continuity.

    Args:
        session_id: The session ID
        limit: How many recent entries to return (default 20)
    """
    ensure_db()
    db = get_session(DB_PATH)
    entries = (
        db.query(NarrativeLog)
        .filter_by(session_id=session_id)
        .order_by(NarrativeLog.id.desc())
        .limit(limit)
        .all()
    )
    db.close()

    if not entries:
        return "No narrative log entries yet."

    entries.reverse()  # Chronological order
    lines = [f"**Narrative Log** (last {len(entries)} entries):", ""]
    for entry in entries:
        source = entry.source.upper()
        lines.append(f"[{source}] ({entry.entry_type}) {entry.content[:300]}")

    return "\n".join(lines)
