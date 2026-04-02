"""
Character Creation Engine
Builds valid 5e characters from SRD data.
Handles race bonuses, class features, starting equipment, etc.
"""

import json
from dataclasses import dataclass, field

from src.data.srd_loader import get_srd_entry, get_srd_list
from src.engine.dice import ability_modifier, roll_ability_scores, roll_hit_points, standard_array
from src.models.database import Character, get_session

DB_PATH = "game.db"

# Default starting equipment per class (simplified from SRD choices)
# Each item: {"index": srd_index, "name": display_name, "quantity": n, "equipped": bool}
DEFAULT_STARTING_EQUIPMENT = {
    "barbarian": [
        {"index": "greataxe", "name": "Greataxe", "quantity": 1, "equipped": True},
        {"index": "handaxe", "name": "Handaxe", "quantity": 2, "equipped": False},
        {"index": "explorers-pack", "name": "Explorer's Pack", "quantity": 1, "equipped": False},
        {"index": "javelin", "name": "Javelin", "quantity": 4, "equipped": False},
    ],
    "bard": [
        {"index": "rapier", "name": "Rapier", "quantity": 1, "equipped": True},
        {"index": "leather-armor", "name": "Leather Armor", "quantity": 1, "equipped": True},
        {"index": "dagger", "name": "Dagger", "quantity": 1, "equipped": False},
        {"index": "diplomats-pack", "name": "Diplomat's Pack", "quantity": 1, "equipped": False},
    ],
    "cleric": [
        {"index": "mace", "name": "Mace", "quantity": 1, "equipped": True},
        {"index": "scale-mail", "name": "Scale Mail", "quantity": 1, "equipped": True},
        {"index": "shield", "name": "Shield", "quantity": 1, "equipped": True},
        {"index": "light-crossbow", "name": "Light Crossbow", "quantity": 1, "equipped": False},
        {"index": "priests-pack", "name": "Priest's Pack", "quantity": 1, "equipped": False},
    ],
    "druid": [
        {"index": "quarterstaff", "name": "Quarterstaff", "quantity": 1, "equipped": True},
        {"index": "leather-armor", "name": "Leather Armor", "quantity": 1, "equipped": True},
        {"index": "shield", "name": "Shield", "quantity": 1, "equipped": True},
        {"index": "explorers-pack", "name": "Explorer's Pack", "quantity": 1, "equipped": False},
    ],
    "fighter": [
        {"index": "chain-mail", "name": "Chain Mail", "quantity": 1, "equipped": True},
        {"index": "longsword", "name": "Longsword", "quantity": 1, "equipped": True},
        {"index": "shield", "name": "Shield", "quantity": 1, "equipped": True},
        {"index": "light-crossbow", "name": "Light Crossbow", "quantity": 1, "equipped": False},
        {"index": "dungeoneers-pack", "name": "Dungeoneer's Pack", "quantity": 1, "equipped": False},
    ],
    "monk": [
        {"index": "shortsword", "name": "Shortsword", "quantity": 1, "equipped": True},
        {"index": "dart", "name": "Dart", "quantity": 10, "equipped": False},
        {"index": "dungeoneers-pack", "name": "Dungeoneer's Pack", "quantity": 1, "equipped": False},
    ],
    "paladin": [
        {"index": "longsword", "name": "Longsword", "quantity": 1, "equipped": True},
        {"index": "chain-mail", "name": "Chain Mail", "quantity": 1, "equipped": True},
        {"index": "shield", "name": "Shield", "quantity": 1, "equipped": True},
        {"index": "javelin", "name": "Javelin", "quantity": 5, "equipped": False},
        {"index": "priests-pack", "name": "Priest's Pack", "quantity": 1, "equipped": False},
    ],
    "ranger": [
        {"index": "longbow", "name": "Longbow", "quantity": 1, "equipped": True},
        {"index": "scale-mail", "name": "Scale Mail", "quantity": 1, "equipped": True},
        {"index": "shortsword", "name": "Shortsword", "quantity": 2, "equipped": False},
        {"index": "explorers-pack", "name": "Explorer's Pack", "quantity": 1, "equipped": False},
    ],
    "rogue": [
        {"index": "rapier", "name": "Rapier", "quantity": 1, "equipped": True},
        {"index": "leather-armor", "name": "Leather Armor", "quantity": 1, "equipped": True},
        {"index": "dagger", "name": "Dagger", "quantity": 2, "equipped": False},
        {"index": "shortbow", "name": "Shortbow", "quantity": 1, "equipped": False},
        {"index": "burglars-pack", "name": "Burglar's Pack", "quantity": 1, "equipped": False},
    ],
    "sorcerer": [
        {"index": "light-crossbow", "name": "Light Crossbow", "quantity": 1, "equipped": False},
        {"index": "dagger", "name": "Dagger", "quantity": 2, "equipped": False},
        {"index": "dungeoneers-pack", "name": "Dungeoneer's Pack", "quantity": 1, "equipped": False},
    ],
    "warlock": [
        {"index": "light-crossbow", "name": "Light Crossbow", "quantity": 1, "equipped": False},
        {"index": "dagger", "name": "Dagger", "quantity": 2, "equipped": False},
        {"index": "leather-armor", "name": "Leather Armor", "quantity": 1, "equipped": True},
        {"index": "scholars-pack", "name": "Scholar's Pack", "quantity": 1, "equipped": False},
    ],
    "wizard": [
        {"index": "quarterstaff", "name": "Quarterstaff", "quantity": 1, "equipped": True},
        {"index": "scholars-pack", "name": "Scholar's Pack", "quantity": 1, "equipped": False},
        {"index": "dagger", "name": "Dagger", "quantity": 1, "equipped": False},
    ],
}

# Armor AC values for calculating AC with equipment
ARMOR_AC = {
    "leather-armor": {"base": 11, "dex_max": None},       # 11 + DEX
    "scale-mail": {"base": 14, "dex_max": 2},             # 14 + DEX (max 2)
    "chain-mail": {"base": 16, "dex_max": 0},             # 16 flat
    "shield": {"bonus": 2},
}

# Skill -> Ability mapping (5e SRD)
SKILL_ABILITIES = {
    "acrobatics": "dexterity",
    "animal-handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight-of-hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}


@dataclass
class CharacterBlueprint:
    """Intermediate representation during character creation."""
    name: str = ""
    race: str = ""
    subrace: str | None = None
    char_class: str = ""
    alignment: str = "neutral"
    background: str = "acolyte"

    # Ability scores (before racial bonuses)
    base_scores: dict = field(default_factory=dict)
    # Final scores (after racial bonuses)
    final_scores: dict = field(default_factory=dict)

    # Choices made during creation
    skill_proficiencies: list = field(default_factory=list)
    languages: list = field(default_factory=list)
    equipment: list = field(default_factory=list)
    proficiencies: list = field(default_factory=list)
    saving_throws: list = field(default_factory=list)
    features: list = field(default_factory=list)
    traits: list = field(default_factory=list)
    spells_known: list = field(default_factory=list)

    # Computed
    max_hp: int = 0
    armor_class: int = 10
    speed: int = 30
    hit_die: int = 8


def get_available_races() -> list[dict]:
    """Get all available races with their summaries."""
    races = get_srd_list(DB_PATH, "races")
    result = []
    for r in races:
        data = get_srd_entry(DB_PATH, "races", r["index"])
        bonuses = {}
        for ab in data.get("ability_bonuses", []):
            ability = ab["ability_score"]["index"].upper()
            bonuses[ability] = ab["bonus"]
        result.append({
            "index": r["index"],
            "name": r["name"],
            "speed": data.get("speed", 30),
            "size": data.get("size", "Medium"),
            "ability_bonuses": bonuses,
            "languages": [l["name"] for l in data.get("languages", [])],
            "traits": [t["name"] for t in data.get("traits", [])],
        })
    return result


def get_available_classes() -> list[dict]:
    """Get all available classes with their summaries."""
    classes = get_srd_list(DB_PATH, "classes")
    result = []
    for c in classes:
        data = get_srd_entry(DB_PATH, "classes", c["index"])
        result.append({
            "index": c["index"],
            "name": c["name"],
            "hit_die": data.get("hit_die", 8),
            "saving_throws": [s["name"] for s in data.get("saving_throws", [])],
            "proficiencies": [p["name"] for p in data.get("proficiencies", [])],
        })
    return result


def get_class_skill_choices(class_index: str) -> dict:
    """Get the skill proficiency choices for a class."""
    data = get_srd_entry(DB_PATH, "classes", class_index)
    if not data:
        return {"choose": 0, "options": []}

    for choice in data.get("proficiency_choices", []):
        # Find the skill choice (not tool proficiencies etc.)
        desc = choice.get("desc", "")
        options = []
        from_data = choice.get("from", {})
        if from_data.get("option_set_type") == "options_array":
            for opt in from_data.get("options", []):
                if opt.get("option_type") == "reference":
                    item = opt.get("item", {})
                    idx = item.get("index", "")
                    if idx.startswith("skill-"):
                        options.append({
                            "index": idx.replace("skill-", ""),
                            "name": item.get("name", "").replace("Skill: ", ""),
                        })
        if options:
            return {
                "choose": choice.get("choose", 2),
                "options": options,
            }

    return {"choose": 0, "options": []}


def apply_race(blueprint: CharacterBlueprint) -> None:
    """Apply racial bonuses and traits to the blueprint."""
    race_data = get_srd_entry(DB_PATH, "races", blueprint.race)
    if not race_data:
        return

    # Speed
    blueprint.speed = race_data.get("speed", 30)

    # Ability score bonuses
    blueprint.final_scores = dict(blueprint.base_scores)
    for ab in race_data.get("ability_bonuses", []):
        ability = ab["ability_score"]["index"]
        bonus = ab["bonus"]
        if ability in blueprint.final_scores:
            blueprint.final_scores[ability] += bonus

    # Languages
    for lang in race_data.get("languages", []):
        if lang["index"] not in blueprint.languages:
            blueprint.languages.append(lang["index"])

    # Racial traits
    for trait in race_data.get("traits", []):
        blueprint.traits.append(trait["index"])

    # Subrace bonuses
    if blueprint.subrace:
        subrace_data = get_srd_entry(DB_PATH, "subraces", blueprint.subrace)
        if subrace_data:
            for ab in subrace_data.get("ability_bonuses", []):
                ability = ab["ability_score"]["index"]
                bonus = ab["bonus"]
                if ability in blueprint.final_scores:
                    blueprint.final_scores[ability] += bonus


def apply_class(blueprint: CharacterBlueprint) -> None:
    """Apply class features to the blueprint."""
    class_data = get_srd_entry(DB_PATH, "classes", blueprint.char_class)
    if not class_data:
        return

    # Hit die
    blueprint.hit_die = class_data.get("hit_die", 8)

    # Saving throws
    for st in class_data.get("saving_throws", []):
        blueprint.saving_throws.append(st["index"])

    # Proficiencies (armor, weapons, tools)
    for prof in class_data.get("proficiencies", []):
        blueprint.proficiencies.append(prof["index"])

    # HP: level 1 = max hit die + CON modifier
    con_mod = ability_modifier(blueprint.final_scores.get("con", 10))
    blueprint.max_hp = blueprint.hit_die + con_mod

    # Starting equipment
    default_gear = DEFAULT_STARTING_EQUIPMENT.get(blueprint.char_class, [])
    blueprint.equipment = [dict(item) for item in default_gear]  # Deep copy

    # Calculate AC from equipped armor
    dex_mod = ability_modifier(blueprint.final_scores.get("dex", 10))
    base_ac = 10 + dex_mod  # Unarmored
    shield_bonus = 0

    for item in blueprint.equipment:
        if not item.get("equipped"):
            continue
        idx = item.get("index", "")
        if idx in ARMOR_AC:
            armor_info = ARMOR_AC[idx]
            if "base" in armor_info:
                # It's body armor
                dex_cap = armor_info.get("dex_max")
                if dex_cap is not None:
                    effective_dex = min(dex_mod, dex_cap)
                else:
                    effective_dex = dex_mod
                base_ac = armor_info["base"] + effective_dex
            elif "bonus" in armor_info:
                # It's a shield
                shield_bonus = armor_info["bonus"]

    blueprint.armor_class = base_ac + shield_bonus


def build_character(
    user_id: int,
    name: str,
    race: str,
    char_class: str,
    ability_scores: dict[str, int],
    skill_choices: list[str],
    subrace: str | None = None,
    alignment: str = "neutral",
    use_standard_array: bool = False,
) -> Character:
    """
    Build a complete character from player choices.
    Returns a Character ORM object ready to save.
    """
    blueprint = CharacterBlueprint(
        name=name,
        race=race,
        subrace=subrace,
        char_class=char_class,
        alignment=alignment,
        base_scores=ability_scores,
        final_scores=dict(ability_scores),
        skill_proficiencies=skill_choices,
    )

    # Apply race and class
    apply_race(blueprint)
    apply_class(blueprint)

    # Build the Character object
    character = Character(
        user_id=user_id,
        name=name,
        race=race,
        subrace=subrace,
        char_class=char_class,
        level=1,
        alignment=alignment,
        strength=blueprint.final_scores.get("str", 10),
        dexterity=blueprint.final_scores.get("dex", 10),
        constitution=blueprint.final_scores.get("con", 10),
        intelligence=blueprint.final_scores.get("int", 10),
        wisdom=blueprint.final_scores.get("wis", 10),
        charisma=blueprint.final_scores.get("cha", 10),
        max_hp=blueprint.max_hp,
        current_hp=blueprint.max_hp,
        armor_class=blueprint.armor_class,
        speed=blueprint.speed,
        hit_dice_remaining=1,
        proficiencies=json.dumps(blueprint.proficiencies),
        skill_proficiencies=json.dumps(blueprint.skill_proficiencies),
        languages=json.dumps(blueprint.languages),
        saving_throw_proficiencies=json.dumps(blueprint.saving_throws),
        equipment=json.dumps(blueprint.equipment),
        features=json.dumps(blueprint.features),
        traits=json.dumps(blueprint.traits),
        spells_known=json.dumps(blueprint.spells_known),
    )

    return character


if __name__ == "__main__":
    print("=== Character Creation Test ===\n")

    print("Available Races:")
    for r in get_available_races():
        print(f"  {r['name']}: {r['ability_bonuses']}, Speed {r['speed']}, Traits: {r['traits'][:3]}")

    print("\nAvailable Classes:")
    for c in get_available_classes():
        print(f"  {c['name']}: d{c['hit_die']}, Saves: {c['saving_throws']}")

    print("\nFighter Skill Choices:")
    choices = get_class_skill_choices("fighter")
    print(f"  Choose {choices['choose']} from: {[o['name'] for o in choices['options']]}")

    print("\n--- Building a test character ---")
    scores = {"str": 15, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 8}
    char = build_character(
        user_id=1,
        name="Thorin Ironforge",
        race="dwarf",
        char_class="fighter",
        subrace="hill-dwarf",
        ability_scores=scores,
        skill_choices=["athletics", "perception"],
        alignment="lawful-good",
    )

    print(f"\n  Name: {char.name}")
    print(f"  Race: {char.race} ({char.subrace})")
    print(f"  Class: {char.char_class}")
    print(f"  STR: {char.strength} ({ability_modifier(char.strength):+d})")
    print(f"  DEX: {char.dexterity} ({ability_modifier(char.dexterity):+d})")
    print(f"  CON: {char.constitution} ({ability_modifier(char.constitution):+d})")
    print(f"  INT: {char.intelligence} ({ability_modifier(char.intelligence):+d})")
    print(f"  WIS: {char.wisdom} ({ability_modifier(char.wisdom):+d})")
    print(f"  CHA: {char.charisma} ({ability_modifier(char.charisma):+d})")
    print(f"  HP: {char.current_hp}/{char.max_hp}")
    print(f"  AC: {char.armor_class}")
    print(f"  Speed: {char.speed} ft")
    print(f"  Skills: {json.loads(char.skill_proficiencies)}")
    print(f"  Saves: {json.loads(char.saving_throw_proficiencies)}")
    print(f"  Languages: {json.loads(char.languages)}")
    print(f"  Proficiencies: {json.loads(char.proficiencies)}")

    print("\n  Game State for AI:")
    print(f"  {json.dumps(char.to_game_state(), indent=2)}")
