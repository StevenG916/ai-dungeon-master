"""Character creation and management tools."""

import json

from src.mcp.server import mcp, ensure_db
from src.engine.character_creation import (
    get_available_races,
    get_available_classes,
    get_class_skill_choices,
    build_character,
)
from src.engine.dice import roll_ability_scores, standard_array
from src.models.database import Character, User, get_session

DB_PATH = "game.db"


@mcp.tool()
def list_races() -> str:
    """List all available D&D 5e races with their ability bonuses, speed, and traits.
    Use this when helping a player choose their race during character creation."""
    ensure_db()
    races = get_available_races()
    lines = []
    for r in races:
        bonuses = ", ".join(f"{k} +{v}" for k, v in r["ability_bonuses"].items())
        traits = ", ".join(r["traits"][:5]) if r["traits"] else "None"
        lines.append(
            f"**{r['name']}** ({r['index']})\n"
            f"  Ability Bonuses: {bonuses}\n"
            f"  Speed: {r['speed']} ft | Size: {r['size']}\n"
            f"  Languages: {', '.join(r['languages'])}\n"
            f"  Traits: {traits}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def list_classes() -> str:
    """List all available D&D 5e classes with hit dice, saving throws, and proficiencies.
    Use this when helping a player choose their class during character creation."""
    ensure_db()
    classes = get_available_classes()
    lines = []
    for c in classes:
        saves = ", ".join(c["saving_throws"])
        profs = ", ".join(c["proficiencies"][:5])
        lines.append(
            f"**{c['name']}** ({c['index']})\n"
            f"  Hit Die: d{c['hit_die']}\n"
            f"  Saving Throws: {saves}\n"
            f"  Proficiencies: {profs}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def get_class_skills(class_name: str) -> str:
    """Get the skill proficiency options for a specific class.
    Returns how many skills to choose and the available options.

    Args:
        class_name: The class index (e.g. "fighter", "rogue", "wizard")
    """
    ensure_db()
    choices = get_class_skill_choices(class_name)
    if choices["choose"] == 0:
        return f"No skill choices found for class '{class_name}'."
    options = ", ".join(o["name"] for o in choices["options"])
    return f"Choose {choices['choose']} skills from: {options}"


@mcp.tool()
def roll_ability_scores_tool(method: str = "roll") -> str:
    """Roll or generate ability scores for character creation.

    Args:
        method: "roll" for 4d6-drop-lowest (6 times), or "standard" for the standard array [15,14,13,12,10,8]
    """
    if method == "standard":
        scores = standard_array()
        return f"Standard Array: {scores}\nAssign these to STR, DEX, CON, INT, WIS, CHA in any order."
    else:
        scores = roll_ability_scores()
        return f"Rolled (4d6 drop lowest x6): {scores}\nAssign these to STR, DEX, CON, INT, WIS, CHA in any order."


@mcp.tool()
def create_character(
    name: str,
    race: str,
    char_class: str,
    ability_scores: str,
    skill_choices: str,
    subrace: str = "",
    alignment: str = "neutral",
) -> str:
    """Create a new character with the given choices. Call this after the player has decided on all their options.

    Args:
        name: Character name (e.g. "Thorin Ironforge")
        race: Race index (e.g. "dwarf", "elf", "human")
        char_class: Class index (e.g. "fighter", "rogue", "wizard")
        ability_scores: JSON object mapping ability to score, e.g. {"str": 15, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 8}
        skill_choices: JSON array of skill names, e.g. ["athletics", "perception"]
        subrace: Optional subrace index (e.g. "hill-dwarf", "high-elf")
        alignment: Optional alignment (e.g. "chaotic-good", "lawful-neutral")
    """
    ensure_db()
    db = get_session(DB_PATH)

    # Ensure a default user exists
    user = db.query(User).filter_by(username="player1").first()
    if not user:
        user = User(username="player1", display_name="Player", password_hash="temp")
        db.add(user)
        db.commit()

    scores = json.loads(ability_scores)
    skills = json.loads(skill_choices)

    char = build_character(
        user_id=user.id,
        name=name,
        race=race,
        char_class=char_class,
        ability_scores=scores,
        skill_choices=skills,
        subrace=subrace or None,
        alignment=alignment,
    )
    db.add(char)
    db.commit()

    from src.engine.dice import ability_modifier

    result = (
        f"Character created: **{char.name}**\n"
        f"Race: {char.race}{' (' + char.subrace + ')' if char.subrace else ''} | "
        f"Class: {char.char_class} | Level: {char.level}\n"
        f"HP: {char.current_hp}/{char.max_hp} | AC: {char.armor_class} | Speed: {char.speed} ft\n\n"
        f"**Ability Scores:**\n"
        f"  STR: {char.strength} ({ability_modifier(char.strength):+d})\n"
        f"  DEX: {char.dexterity} ({ability_modifier(char.dexterity):+d})\n"
        f"  CON: {char.constitution} ({ability_modifier(char.constitution):+d})\n"
        f"  INT: {char.intelligence} ({ability_modifier(char.intelligence):+d})\n"
        f"  WIS: {char.wisdom} ({ability_modifier(char.wisdom):+d})\n"
        f"  CHA: {char.charisma} ({ability_modifier(char.charisma):+d})\n\n"
        f"Skills: {', '.join(skills)}\n"
        f"Equipment: {', '.join(item['name'] for item in json.loads(char.equipment))}\n\n"
        f"Character ID: {char.id}"
    )
    db.close()
    return result


@mcp.tool()
def list_characters() -> str:
    """List all existing characters. Use this to check if the player already has a character."""
    ensure_db()
    db = get_session(DB_PATH)
    characters = db.query(Character).filter_by(is_alive=True).all()
    db.close()

    if not characters:
        return "No characters found. Create one to start playing!"

    lines = []
    for c in characters:
        lines.append(
            f"**{c.name}** (ID: {c.id})\n"
            f"  {c.race} {c.char_class} | Level {c.level} | "
            f"HP: {c.current_hp}/{c.max_hp} | AC: {c.armor_class}"
        )
    return "\n\n".join(lines)
