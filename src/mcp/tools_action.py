"""Core gameplay action tool — the heart of the MCP server."""

import json

from src.mcp.server import mcp, ensure_db
from src.engine.game_session import GameEngine


@mcp.tool()
def game_action(session_id: int, action_type: str, params: str = "{}") -> str:
    """Execute a player action in the game. This is the main gameplay tool.
    The engine resolves ALL mechanics (dice rolls, damage, success/failure).
    You then narrate the results dramatically.

    Args:
        session_id: The active session ID
        action_type: One of: move, look, search, talk, attack, skill_check, pick_up, rest, free_action
        params: JSON object with action-specific parameters:
            - move: {"direction": "north"} or {"direction": "cave_entrance"} (scene ID)
            - look: {"target": "the altar"} (optional, omit to look around)
            - search: {"skill": "perception"} or {"skill": "investigation"}
            - talk: {"npc": "Bram", "topic": "goblin raids"}
            - attack: {"target": "Goblin 1", "weapon": "longsword"}
            - skill_check: {"skill": "athletics", "dc": 12}
            - pick_up: {"item": "rusty key"}
            - rest: {"type": "short"} or {"type": "long"}
            - free_action: {"text": "I try to kick down the door"}
    """
    ensure_db()
    engine = GameEngine(session_id)

    if not engine.session:
        return f"Error: Session {session_id} not found."

    action_params = json.loads(params)
    result = engine.process_action(action_type, action_params)

    # Build the full context for narration
    context = engine.build_ai_context(result)

    # Format the response with everything Claude needs to narrate
    lines = []

    # Action outcome
    lines.append(f"**Action: {action_type}** — {'Success' if result.success else 'Failed'}")
    if result.error:
        lines.append(f"Error: {result.error}")

    lines.append(f"\n**What happened:** {result.narrative_context}")

    # Dice rolls
    if result.roll_results:
        lines.append("\n**Rolls:**")
        for roll in result.roll_results:
            roll_type = roll.get("type", "?")
            if roll_type == "attack":
                hit_text = "HIT" if roll.get("hit") else "MISS"
                crit_text = " (CRITICAL!)" if roll.get("critical") else ""
                lines.append(
                    f"  Attack: {roll.get('roll', '?')} vs AC {roll.get('target_ac', '?')} -> "
                    f"{hit_text}{crit_text}"
                )
                if roll.get("hit"):
                    lines.append(f"    Damage: {roll.get('damage', 0)} {roll.get('damage_type', '')}")
            elif roll_type == "skill_check":
                success_text = "SUCCESS" if roll.get("success") else "FAILURE"
                dc_text = f" vs DC {roll['dc']}" if roll.get("dc") else ""
                lines.append(
                    f"  {roll.get('skill', 'Check')}: {roll.get('roll', '?')} "
                    f"(total: {roll.get('total', '?')}){dc_text} -> {success_text}"
                )
            elif roll_type == "monster_attack":
                hit_text = "HIT" if roll.get("hit") else "MISS"
                crit_text = " (CRITICAL!)" if roll.get("critical") else ""
                lines.append(
                    f"  {roll.get('attacker', '?')} attacks: "
                    f"{roll.get('roll', '?')} vs AC {roll.get('target_ac', '?')} -> "
                    f"{hit_text}{crit_text}"
                )
                if roll.get("hit"):
                    lines.append(f"    Damage: {roll.get('damage', 0)} {roll.get('damage_type', '')}")

    # Items found
    if result.items_found:
        lines.append("\n**Discoveries:**")
        for item in result.items_found:
            dc_text = f" (DC {item['dc']})" if item.get("dc") else ""
            lines.append(f"  Found {item['type']}: {item.get('name', item.get('description', '?'))}{dc_text}")

    # State changes — things that have changed in the current scene
    scene = context.get("scene", {})
    scene_changes = scene.get("state_changes", [])
    if scene_changes:
        lines.append("\n**Scene State Changes (narrate these — the scene has changed):**")
        for change in scene_changes:
            lines.append(f"  - {change}")

    dead = scene.get("dead_npcs", [])
    if dead:
        lines.append(f"**Dead NPCs (do NOT describe as alive):** {', '.join(dead)}")

    # Scene transition
    if result.scene_changed:
        lines.append(f"\n**New Scene: {scene.get('name', '?')}**")
        lines.append(scene.get("description", ""))

        if scene.get("ai_notes"):
            lines.append(f"\n[DM Notes: {scene['ai_notes']}]")

        npcs = scene.get("npcs", [])
        if npcs:
            lines.append(f"\nNPCs: {', '.join(n['name'] + ' (' + n['disposition'] + ')' for n in npcs)}")

        exits = scene.get("exits", [])
        if exits:
            lines.append(f"Exits: {', '.join(e['direction'] + ': ' + e.get('description', '') for e in exits)}")

        items = scene.get("items", [])
        if items:
            lines.append(f"Items: {', '.join(i['name'] for i in items)}")

    # Combat triggers — auto-triggered encounters (on_enter)
    if result.combat_started:
        encounters = context.get("scene", {}).get("pending_encounters", [])
        if encounters:
            enc = encounters[0]
            lines.append(f"\n** COMBAT TRIGGERED!** Encounter ID: `{enc.get('id', '?')}`")
            lines.append(f"Description: {enc.get('description', '')}")
            lines.append("-> You MUST now call `start_combat` with this encounter ID!")

    # Always show available manual encounters when entering a scene or looking around
    # This is critical — manual encounters need the DM to decide when to trigger them
    if result.scene_changed or action_type in ("look", "search"):
        scene = context.get("scene", {})
        # Get ALL encounters from the adventure, not just pending_encounters (which filters by trigger)
        if engine.adventure:
            adventure_scene = engine.adventure.scenes.get(engine.session.current_scene_id)
            if adventure_scene:
                flags = engine.get_flags()
                manual_encounters = []
                for enc in adventure_scene.encounters:
                    flag_key = f"encounter_{enc.id}_complete"
                    if enc.once and flags.get(flag_key):
                        continue
                    manual_encounters.append({
                        "id": enc.id,
                        "description": enc.description,
                        "trigger": enc.trigger,
                    })
                if manual_encounters:
                    lines.append("\n**Available Encounters:**")
                    for enc in manual_encounters:
                        trigger_note = f" [{enc['trigger']}]" if enc['trigger'] != 'manual' else " [start when narratively appropriate]"
                        lines.append(f"  - `{enc['id']}`: {enc['description']}{trigger_note}")
                    lines.append("-> Call `start_combat(session_id, encounter_id)` to begin an encounter.")

    if result.combat_ended:
        lines.append("\n** COMBAT ENDED** — All enemies defeated!")

    # Damage summary
    if result.damage_dealt:
        lines.append(f"\nDamage dealt: {result.damage_dealt}")
    if result.damage_taken:
        lines.append(f"Damage taken: {result.damage_taken}")

    # Character status
    char = context.get("character", {})
    if char:
        lines.append(f"\n**{char.get('name', '?')} HP: {char.get('hp', '?')}**")

    return "\n".join(lines)
