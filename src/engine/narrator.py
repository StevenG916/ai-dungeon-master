"""
AI Narrator
Builds prompts from game context and generates narrative via Claude API.
The AI handles ONLY narrative — all mechanics are resolved by the engine first.
"""

import json
import os
from dataclasses import dataclass

# Will use httpx for async API calls in the FastAPI app
# For now, synchronous version for testing
import httpx

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are the Dungeon Master (narrator) for a solo D&D 5th Edition adventure. Your role is to bring the game world to life through vivid, immersive narration.

CRITICAL RULES:
- You NEVER decide mechanical outcomes. All dice rolls, damage, hit/miss, skill check results are provided to you as facts. Narrate them dramatically but never change them.
- You NEVER invent rooms, exits, NPCs, items, or encounters that aren't in the scene data provided. The adventure module is the source of truth.
- You NEVER tell the player their exact HP, AC, or numbers unless they ask. Describe injuries narratively ("you're badly wounded" not "you have 3 HP").
- You DO describe the scene, voice NPCs, narrate combat dramatically, react to player creativity, and set the mood.
- You DO describe what the player sees, hears, smells, and feels.
- You DO roleplay NPCs based on their description and dialogue hints.
- Keep responses concise but atmospheric — aim for 2-4 paragraphs typically.
- End your responses with a subtle prompt for what the player might do next, without being heavy-handed about it.
- For combat, describe attacks cinematically. A miss isn't just "you miss" — describe the blade glancing off armor or the goblin ducking.
- Use second person ("you") to address the player character.

TONE: Classic fantasy adventure. Serious but not grimdark. Moments of humor are welcome. Think of a skilled human DM running a game for a friend."""


def build_narrator_prompt(ai_context: dict) -> list[dict]:
    """
    Build the message list for the Claude API from game context.
    The context contains everything the AI needs to know.
    """
    messages = []

    # Build the context message
    scene = ai_context.get("scene", {})
    character = ai_context.get("character", {})
    last_action = ai_context.get("last_action", {})
    combat = ai_context.get("combat", {})
    history = ai_context.get("recent_history", [])

    # Construct the information block
    info_parts = []

    # Scene info
    info_parts.append(f"## Current Scene: {scene.get('name', 'Unknown')}")
    info_parts.append(f"Description: {scene.get('description', '')}")
    if scene.get('ai_notes'):
        info_parts.append(f"DM Notes: {scene.get('ai_notes')}")
    info_parts.append(f"Lighting: {scene.get('lighting', 'normal')}")

    # Exits
    exits = scene.get("exits", [])
    if exits:
        exit_strs = [f"- {e['direction']}: {e['description']}" for e in exits]
        info_parts.append(f"Exits:\n" + "\n".join(exit_strs))

    # NPCs present
    npcs = scene.get("npcs", [])
    if npcs:
        for npc in npcs:
            info_parts.append(
                f"NPC Present: {npc['name']} — {npc['description']} "
                f"(Disposition: {npc['disposition']})"
            )
            if npc.get("dialogue_hints"):
                info_parts.append(f"  What they know: {'; '.join(npc['dialogue_hints'])}")

    # Items visible
    items = scene.get("items", [])
    if items:
        item_strs = [f"- {i['name']}: {i['description']}" for i in items]
        info_parts.append(f"Visible Items:\n" + "\n".join(item_strs))

    # Active events
    events = scene.get("active_events", [])
    if events:
        for event in events:
            info_parts.append(f"EVENT: {event['description']}")
            if event.get("narrative"):
                info_parts.append(f"  Narrative cue: {event['narrative']}")

    # Character info
    info_parts.append(f"\n## Player Character: {character.get('name', 'Unknown')}")
    info_parts.append(f"Race: {character.get('race')}, Class: {character.get('class')}, Level: {character.get('level')}")
    info_parts.append(f"HP: {character.get('hp')}, AC: {character.get('ac')}")

    # Combat state
    if ai_context.get("in_combat") and combat:
        info_parts.append(f"\n## COMBAT IS ACTIVE")
        info_parts.append(f"Initiative Order: {json.dumps(combat.get('initiative_order', []))}")
        for enemy in combat.get("enemies", []):
            status = "alive" if enemy["alive"] else "DEAD"
            info_parts.append(f"Enemy: {enemy['name']} — HP: {enemy['hp']}, AC: {enemy['ac']}, Status: {status}")

    # What just happened (the action result)
    if last_action:
        info_parts.append(f"\n## WHAT JUST HAPPENED")
        info_parts.append(f"Action: {last_action.get('type', 'unknown')}")
        info_parts.append(f"Result: {'Success' if last_action.get('success') else 'Failure'}")
        info_parts.append(f"Details: {last_action.get('narrative_context', '')}")

        # Roll results
        for roll in last_action.get("rolls", []):
            if roll.get("type") == "attack":
                hit_miss = "HIT" if roll["hit"] else "MISS"
                info_parts.append(
                    f"Player Attack Roll: {roll['roll']} vs AC {roll['target_ac']} = {hit_miss}"
                )
                if roll["hit"]:
                    info_parts.append(f"Damage: {roll['damage']} {roll['damage_type']}")
                if roll.get("critical"):
                    info_parts.append("CRITICAL HIT!")
            elif roll.get("type") == "monster_attack":
                hit_miss = "HIT" if roll.get("hit") else "MISS"
                info_parts.append(
                    f"Monster Attack: {roll.get('attacker', '?')} uses {roll.get('action', 'attack')} — "
                    f"{roll.get('roll', '?')} vs AC {roll.get('target_ac', '?')} = {hit_miss}"
                )
                if roll.get("hit"):
                    info_parts.append(f"  Deals {roll.get('damage', 0)} {roll.get('damage_type', '')} damage to the player!")
                if roll.get("critical"):
                    info_parts.append("  CRITICAL HIT on the player!")
            elif roll.get("type") == "skill_check":
                info_parts.append(
                    f"Skill Check ({roll['skill']}): {roll['roll']}"
                    + (f" vs DC {roll['dc']} = {'SUCCESS' if roll['success'] else 'FAILURE'}" if 'dc' in roll else "")
                )

        # Items found
        if last_action.get("items_found"):
            for item in last_action["items_found"]:
                info_parts.append(f"DISCOVERED: {item['name']} — {item['description']} (DC {item.get('dc', '?')})")

        if last_action.get("combat_started"):
            info_parts.append("COMBAT HAS JUST STARTED! Describe the enemies appearing and the tension.")

        if last_action.get("combat_ended"):
            info_parts.append("ALL ENEMIES DEFEATED! Describe the aftermath of combat.")

    # Recent narrative history for continuity
    if history:
        info_parts.append(f"\n## Recent History (for continuity)")
        for h in history[-5:]:  # Last 5 entries only
            info_parts.append(f"[{h['source']}] {h['content'][:200]}")

    context_block = "\n".join(info_parts)

    # The user message instructs the AI what to do
    if last_action:
        action_type = last_action.get("type", "")
        if action_type == "move" and last_action.get("success"):
            user_msg = f"The player has just entered a new area. Describe the scene they see upon arrival.\n\n{context_block}"
        elif action_type == "talk":
            user_msg = f"The player is talking to an NPC. Roleplay the NPC's response based on their personality and knowledge.\n\n{context_block}"
        elif action_type == "attack":
            user_msg = f"Narrate this combat action dramatically. Describe the attack and its result.\n\n{context_block}"
        elif action_type == "search":
            user_msg = f"The player searched the area. Describe what they find (or don't find).\n\n{context_block}"
        elif action_type == "skill_check":
            user_msg = f"Narrate the result of this skill check.\n\n{context_block}"
        elif action_type == "free_action":
            user_msg = f"The player is attempting a creative action. Narrate what happens based on the scene context.\n\n{context_block}"
        elif action_type == "rest":
            user_msg = f"The player is resting. Describe the passage of time and recovery.\n\n{context_block}"
        else:
            user_msg = f"Narrate what happens next based on the current game state.\n\n{context_block}"
    else:
        # Opening narration
        intro = ai_context.get("adventure_intro", "")
        user_msg = f"This is the start of the adventure. Deliver the opening narration and describe the first scene.\n\nAdventure Intro: {intro}\n\n{context_block}"

    messages.append({"role": "user", "content": user_msg})

    return messages


def generate_narrative(
    ai_context: dict,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1000,
) -> str:
    """
    Call the Claude API to generate narrative from game context.
    Returns the narrative text.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _mock_narrative(ai_context)

    messages = build_narrator_prompt(ai_context)

    try:
        response = httpx.post(
            ANTHROPIC_API_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        # Extract text from response
        text_parts = [
            block["text"]
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        return "\n".join(text_parts)

    except Exception as e:
        return f"[AI Error: {str(e)}] The dungeon master pauses momentarily..."


def _mock_narrative(ai_context: dict) -> str:
    """Generate a mock narrative when no API key is available (for testing)."""
    scene = ai_context.get("scene", {})
    last_action = ai_context.get("last_action", {})
    character = ai_context.get("character", {})

    parts = []
    parts.append(f"[MOCK AI NARRATIVE - No API key set]")
    parts.append(f"Scene: {scene.get('name', 'Unknown')}")

    if last_action:
        action_type = last_action.get("type", "")
        if action_type == "move":
            parts.append(f"\n{scene.get('description', 'You enter a new area.')}")
            npcs = scene.get("npcs", [])
            if npcs:
                parts.append(f"You see {', '.join(n['name'] for n in npcs)} here.")
        elif action_type == "attack":
            ctx = last_action.get("narrative_context", "")
            parts.append(f"\n{ctx}")
        elif action_type == "talk":
            parts.append(f"\nThe NPC responds to your inquiry.")
        elif action_type == "search":
            items = last_action.get("items_found", [])
            if items:
                parts.append(f"\nYou found: {', '.join(i['name'] for i in items)}")
            else:
                parts.append("\nYou search thoroughly but find nothing of note.")
        else:
            parts.append(f"\n{last_action.get('narrative_context', 'Something happens.')}")
    else:
        parts.append(f"\n{scene.get('description', 'The adventure begins...')}")

    parts.append(f"\nWhat do you do?")
    return "\n".join(parts)


if __name__ == "__main__":
    # Test prompt building
    test_context = {
        "adventure_name": "The Goblin Cave",
        "scene": {
            "name": "Cave Entrance",
            "description": "A dark cave mouth gapes open in the hillside. The stench of goblins drifts out.",
            "ai_notes": "Tense moment. The lookout goblin is hidden on a ledge.",
            "lighting": "dim",
            "exits": [
                {"direction": "back", "description": "The trail back to the road", "locked": False},
                {"direction": "inside", "description": "Into the dark cave", "locked": False},
            ],
            "npcs": [],
            "items": [],
            "pending_encounters": [],
            "active_events": [],
        },
        "character": {
            "name": "Kira Shadowstep",
            "race": "elf",
            "class": "rogue",
            "level": 1,
            "hp": "9/9",
            "ac": 14,
        },
        "in_combat": True,
        "combat": {
            "initiative_order": [
                {"name": "Snik the Lookout", "initiative": 18, "is_player": False},
                {"name": "Kira Shadowstep", "initiative": 16, "is_player": True},
            ],
            "enemies": [
                {"name": "Snik the Lookout", "hp": "3/7", "alive": True, "ac": 15},
            ],
        },
        "last_action": {
            "type": "attack",
            "success": True,
            "narrative_context": "Player attacks Snik the Lookout with shortsword. Hit. Dealt 4 damage. Snik the Lookout has 3 HP remaining.",
            "rolls": [{
                "type": "attack",
                "roll": "[18] + 5 = 23",
                "total": 23,
                "target_ac": 15,
                "hit": True,
                "critical": False,
                "damage": 4,
                "damage_roll": "[2] + 3 = 4",
                "damage_type": "piercing",
            }],
        },
        "recent_history": [],
        "story_flags": {},
    }

    print("=== AI Narrator Test ===\n")
    print("--- Built Prompt ---")
    messages = build_narrator_prompt(test_context)
    for msg in messages:
        print(f"\n[{msg['role']}]:")
        print(msg['content'][:2000])

    print("\n\n--- Mock Narrative ---")
    narrative = generate_narrative(test_context)
    print(narrative)
