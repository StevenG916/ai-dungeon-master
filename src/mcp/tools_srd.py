"""SRD reference data lookup tool."""

import json

from src.mcp.server import mcp, ensure_db
from src.data.srd_loader import get_srd_entry, get_srd_list, search_srd

DB_PATH = "game.db"


@mcp.tool()
def lookup_srd(data_type: str, query: str = "") -> str:
    """Look up D&D 5e reference data from the SRD.
    Use this to check monster stats, spell details, equipment properties, etc.

    Args:
        data_type: Type of data to look up. One of: monsters, spells, races, classes, equipment, magic_items, conditions, features, traits, subraces, subclasses
        query: Search term or exact index. Leave empty to list all entries of that type. Examples: "goblin", "fireball", "longsword"
    """
    ensure_db()

    if not query:
        # List all entries of this type
        entries = get_srd_list(DB_PATH, data_type)
        if not entries:
            return f"No entries found for type '{data_type}'."
        names = [f"{e['name']} ({e['index']})" for e in entries[:50]]
        total = len(entries)
        result = f"**{data_type}** ({total} entries):\n" + "\n".join(names)
        if total > 50:
            result += f"\n... and {total - 50} more. Use a query to search."
        return result

    # Try exact lookup first
    entry = get_srd_entry(DB_PATH, data_type, query)
    if entry:
        return _format_srd_entry(data_type, entry)

    # Try search
    results = search_srd(DB_PATH, data_type, query)
    if not results:
        return f"No {data_type} found matching '{query}'."

    if len(results) == 1:
        # Single match — show full details
        full = get_srd_entry(DB_PATH, data_type, results[0]["index"])
        if full:
            return _format_srd_entry(data_type, full)

    # Multiple matches — list them
    names = [f"{r['name']} ({r['index']})" for r in results[:20]]
    return f"Found {len(results)} matches for '{query}':\n" + "\n".join(names)


def _format_srd_entry(data_type: str, entry: dict) -> str:
    """Format an SRD entry for readable output."""
    if data_type == "monsters":
        return _format_monster(entry)
    elif data_type == "spells":
        return _format_spell(entry)
    elif data_type == "equipment":
        return _format_equipment(entry)
    else:
        # Generic formatting — show key fields
        lines = [f"**{entry.get('name', '?')}** ({entry.get('index', '?')})"]
        if entry.get("desc"):
            desc = entry["desc"]
            if isinstance(desc, list):
                desc = " ".join(desc)
            lines.append(desc[:500])
        return "\n".join(lines)


def _format_monster(m: dict) -> str:
    """Format a monster stat block."""
    ac_entries = m.get("armor_class", [{}])
    ac = ac_entries[0].get("value", "?") if ac_entries else "?"

    lines = [
        f"# {m.get('name', '?')}",
        f"*{m.get('size', '?')} {m.get('type', '?')}, {m.get('alignment', '?')}*",
        "",
        f"**AC:** {ac} | **HP:** {m.get('hit_points', '?')} ({m.get('hit_points_roll', '?')}) | **Speed:** {m.get('speed', {}).get('walk', '?')}",
        "",
        f"STR {m.get('strength', '?')} | DEX {m.get('dexterity', '?')} | CON {m.get('constitution', '?')} | "
        f"INT {m.get('intelligence', '?')} | WIS {m.get('wisdom', '?')} | CHA {m.get('charisma', '?')}",
        "",
        f"**CR:** {m.get('challenge_rating', '?')} ({m.get('xp', '?')} XP)",
    ]

    # Actions
    actions = m.get("actions", [])
    if actions:
        lines.append("\n**Actions:**")
        for a in actions:
            desc = a.get("desc", "")[:200]
            lines.append(f"  **{a.get('name', '?')}:** {desc}")

    return "\n".join(lines)


def _format_spell(s: dict) -> str:
    """Format a spell description."""
    desc = s.get("desc", [])
    if isinstance(desc, list):
        desc = " ".join(desc)

    lines = [
        f"# {s.get('name', '?')}",
        f"*Level {s.get('level', '?')} {s.get('school', {}).get('name', '?')}*",
        "",
        f"**Casting Time:** {s.get('casting_time', '?')}",
        f"**Range:** {s.get('range', '?')}",
        f"**Components:** {', '.join(s.get('components', []))}",
        f"**Duration:** {s.get('duration', '?')}",
        "",
        desc[:500],
    ]
    return "\n".join(lines)


def _format_equipment(e: dict) -> str:
    """Format an equipment entry."""
    lines = [
        f"# {e.get('name', '?')}",
        f"*{e.get('equipment_category', {}).get('name', '?')}*",
    ]

    if e.get("damage"):
        dmg = e["damage"]
        lines.append(f"**Damage:** {dmg.get('damage_dice', '?')} {dmg.get('damage_type', {}).get('name', '')}")

    if e.get("armor_class"):
        ac = e["armor_class"]
        lines.append(f"**AC:** {ac.get('base', '?')} (+ DEX max {ac.get('dex_bonus', '?')})")

    cost = e.get("cost", {})
    if cost:
        lines.append(f"**Cost:** {cost.get('quantity', '?')} {cost.get('unit', '?')}")

    if e.get("weight"):
        lines.append(f"**Weight:** {e['weight']} lb")

    desc = e.get("desc", [])
    if desc:
        if isinstance(desc, list):
            desc = " ".join(desc)
        lines.append(f"\n{desc[:300]}")

    return "\n".join(lines)
