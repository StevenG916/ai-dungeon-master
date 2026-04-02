"""
Game Session Engine
The core state machine that manages the game loop.

Flow:
1. Player submits an action (text input or button press)
2. Engine determines action type (move, attack, talk, search, use item, etc.)
3. Engine resolves mechanics (dice rolls, state changes)
4. Engine builds AI context (scene + character state + action result)
5. AI generates narrative response
6. Narrative + mechanical results sent to player
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from src.data.srd_loader import get_srd_entry
from src.engine.adventure import (
    Adventure,
    check_search_results,
    get_scene_context,
    load_adventure,
)
from src.engine.dice import (
    AttackResult,
    RollResult,
    ability_check,
    ability_modifier,
    attack_roll,
    proficiency_bonus,
    roll_d20,
    roll_dice,
    roll_initiative,
)
from src.models.database import (
    Character,
    CombatEntity,
    GameSession,
    NarrativeLog,
    SessionParticipant,
    get_session,
)

DB_PATH = "game.db"

# Skill -> Ability mapping
SKILL_ABILITIES = {
    "acrobatics": "dexterity", "animal-handling": "wisdom",
    "arcana": "intelligence", "athletics": "strength",
    "deception": "charisma", "history": "intelligence",
    "insight": "wisdom", "intimidation": "charisma",
    "investigation": "intelligence", "medicine": "wisdom",
    "nature": "intelligence", "perception": "wisdom",
    "performance": "charisma", "persuasion": "charisma",
    "religion": "intelligence", "sleight-of-hand": "dexterity",
    "stealth": "dexterity", "survival": "wisdom",
}


class GameMode(str, Enum):
    EXPLORATION = "exploration"
    COMBAT = "combat"
    SOCIAL = "social"
    REST = "rest"


class ActionType(str, Enum):
    MOVE = "move"               # Go to a different scene
    LOOK = "look"               # Examine the current scene
    SEARCH = "search"           # Search for hidden things
    TALK = "talk"               # Talk to an NPC
    ATTACK = "attack"           # Attack a target
    CAST_SPELL = "cast_spell"   # Cast a spell
    USE_ITEM = "use_item"       # Use an item
    PICK_UP = "pick_up"         # Pick up an item
    SKILL_CHECK = "skill_check" # Perform a skill check
    REST = "rest"               # Short or long rest
    FREE_ACTION = "free_action" # Freeform action for AI to interpret
    END_TURN = "end_turn"       # End combat turn


@dataclass
class ActionResult:
    """The result of processing a player action, ready for AI narration."""
    action_type: ActionType
    success: bool = True
    narrative_context: str = ""     # What the AI should know happened
    roll_results: list[dict] = field(default_factory=list)
    state_changes: list[str] = field(default_factory=list)
    flags_set: list[str] = field(default_factory=list)
    scene_changed: bool = False
    new_scene_id: str = ""
    combat_started: bool = False
    combat_ended: bool = False
    items_found: list[dict] = field(default_factory=list)
    damage_dealt: int = 0
    damage_taken: int = 0
    error: str = ""


class GameEngine:
    """Manages a single game session."""

    def __init__(self, session_id: int):
        self.session_id = session_id
        self.db = get_session(DB_PATH)
        self.session: GameSession = self.db.query(GameSession).get(session_id)
        self.adventure: Adventure | None = None
        self._load_adventure()

    def _load_adventure(self):
        """Load the adventure module for this session."""
        if self.session and self.session.adventure_id:
            import glob
            import os
            # Search for adventure file matching the ID
            for pattern in [
                f"adventures/{self.session.adventure_id}.json",
                f"adventures/*{self.session.adventure_id}*.json",
            ]:
                matches = glob.glob(pattern)
                if matches:
                    self.adventure = load_adventure(matches[0])
                    return
            # Try by matching the id inside the json files
            for f in glob.glob("adventures/*.json"):
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    if data.get("id") == self.session.adventure_id:
                        self.adventure = load_adventure(f)
                        return
                except Exception:
                    pass

    def get_character(self) -> Character | None:
        """Get the player's character for this session."""
        participant = (
            self.db.query(SessionParticipant)
            .filter_by(session_id=self.session_id, is_active=True)
            .first()
        )
        if participant:
            return self.db.query(Character).get(participant.character_id)
        return None

    def get_flags(self) -> dict:
        """Get the session's story flags."""
        return json.loads(self.session.story_flags or "{}")

    def set_flag(self, key: str, value=True):
        """Set a story flag."""
        flags = self.get_flags()
        flags[key] = value
        self.session.story_flags = json.dumps(flags)
        self.db.commit()

    def get_current_scene_context(self) -> dict:
        """Get the AI context for the current scene."""
        if not self.adventure or not self.session.current_scene_id:
            return {}
        return get_scene_context(
            self.adventure,
            self.session.current_scene_id,
            self.get_flags(),
        )

    def get_combat_entities(self) -> list[CombatEntity]:
        """Get all active combat entities in this session."""
        return (
            self.db.query(CombatEntity)
            .filter_by(session_id=self.session_id, is_active=True)
            .all()
        )

    # ------------------------------------------------------------------
    # Action Processing
    # ------------------------------------------------------------------

    def process_action(self, action_type: str, params: dict) -> ActionResult:
        """Main entry point: process a player action and return results."""
        action = ActionType(action_type)

        handlers = {
            ActionType.MOVE: self._handle_move,
            ActionType.LOOK: self._handle_look,
            ActionType.SEARCH: self._handle_search,
            ActionType.TALK: self._handle_talk,
            ActionType.ATTACK: self._handle_attack,
            ActionType.SKILL_CHECK: self._handle_skill_check,
            ActionType.PICK_UP: self._handle_pick_up,
            ActionType.REST: self._handle_rest,
            ActionType.FREE_ACTION: self._handle_free_action,
            ActionType.END_TURN: self._handle_end_turn,
        }

        handler = handlers.get(action)
        if not handler:
            return ActionResult(
                action_type=action,
                success=False,
                error=f"Unknown action type: {action_type}",
            )

        result = handler(params)

        # Auto-trigger monster turns after player attacks in combat
        if (
            action == ActionType.ATTACK
            and self.session.in_combat
            and not result.combat_ended
            and result.success is not None  # Valid action was attempted
        ):
            monster_result = self._process_monster_turns()
            # Merge monster turn info into the result
            result.narrative_context += "\n\n" + monster_result.narrative_context
            result.roll_results.extend(monster_result.roll_results)
            result.damage_taken = monster_result.damage_taken
            if monster_result.combat_ended:
                result.combat_ended = True

        # Auto-end combat if all enemies dead
        if result.combat_ended and self.session.in_combat:
            # Find the active encounter to end it properly
            scene = self.adventure.scenes.get(self.session.current_scene_id) if self.adventure else None
            if scene:
                for enc in scene.encounters:
                    flag_key = f"encounter_{enc.id}_complete"
                    if not self.get_flags().get(flag_key):
                        self.end_combat(enc.id)
                        result.narrative_context += f"\n\nVICTORY! Gained {enc.xp_reward} XP."
                        break

        # Log the action
        self._log_action(action, params, result)

        return result

    def _handle_move(self, params: dict) -> ActionResult:
        """Handle moving to a different scene."""
        direction = params.get("direction", "")
        character = self.get_character()
        scene = self.adventure.scenes.get(self.session.current_scene_id) if self.adventure else None

        if not scene:
            return ActionResult(action_type=ActionType.MOVE, success=False, error="No current scene")

        # Find the exit
        target_exit = None
        flags = self.get_flags()
        for exit in scene.exits:
            if exit.direction.lower() == direction.lower() or exit.target_scene == direction:
                # Check if hidden (must have been discovered)
                if exit.hidden and not flags.get(f"discovered_{exit.target_scene}"):
                    continue
                # Check flag requirements
                if exit.requires_flag and not flags.get(exit.requires_flag):
                    continue
                target_exit = exit
                break

        if not target_exit:
            return ActionResult(
                action_type=ActionType.MOVE,
                success=False,
                narrative_context=f"There's no obvious way to go '{direction}'.",
            )

        # Check if locked
        if target_exit.locked:
            return ActionResult(
                action_type=ActionType.MOVE,
                success=False,
                narrative_context=f"The way is locked. {target_exit.description}",
            )

        # Move to the new scene
        old_scene = self.session.current_scene_id
        self.session.current_scene_id = target_exit.target_scene
        self.db.commit()

        # Set on_enter flag if any
        new_scene = self.adventure.scenes.get(target_exit.target_scene)
        if new_scene and new_scene.on_enter_flag:
            self.set_flag(new_scene.on_enter_flag)

        # Check for on_enter encounters
        new_context = self.get_current_scene_context()
        encounter_triggered = None
        for enc in new_context.get("pending_encounters", []):
            if enc["trigger"] == "on_enter":
                encounter_triggered = enc
                break

        result = ActionResult(
            action_type=ActionType.MOVE,
            success=True,
            scene_changed=True,
            new_scene_id=target_exit.target_scene,
            narrative_context=f"The player moves from {old_scene} to {target_exit.target_scene}. {new_scene.description if new_scene else ''}",
        )

        if encounter_triggered:
            result.combat_started = True
            result.narrative_context += f"\n\nENCOUNTER TRIGGERED: {encounter_triggered['description']}"

        return result

    def _handle_look(self, params: dict) -> ActionResult:
        """Handle examining the current scene or a specific thing."""
        target = params.get("target", "").lower()
        context = self.get_current_scene_context()
        flags = self.get_flags()

        if target:
            # Try to match target to an NPC
            for npc in context.get("npcs", []):
                if target in npc["name"].lower():
                    return ActionResult(
                        action_type=ActionType.LOOK,
                        success=True,
                        narrative_context=(
                            f"Player examines {npc['name']}.\n"
                            f"Description: {npc['description']}\n"
                            f"Disposition: {npc['disposition']}"
                        ),
                    )

            # Try dead NPCs
            for name in context.get("dead_npcs", []):
                if target in name.lower():
                    return ActionResult(
                        action_type=ActionType.LOOK,
                        success=True,
                        narrative_context=f"Player examines the body of {name}. They are dead.",
                    )

            # Try items
            for item in context.get("items", []):
                if target in item["name"].lower():
                    return ActionResult(
                        action_type=ActionType.LOOK,
                        success=True,
                        narrative_context=f"Player examines {item['name']}. {item.get('description', '')}",
                    )

            # Try exits
            for exit in context.get("exits", []):
                if target in exit.get("direction", "").lower() or target in exit.get("description", "").lower():
                    locked = " It appears to be locked." if exit.get("locked") else ""
                    return ActionResult(
                        action_type=ActionType.LOOK,
                        success=True,
                        narrative_context=f"Player examines the {exit['direction']} exit. {exit['description']}{locked}",
                    )

            # No match — still describe the scene with the target noted
            return ActionResult(
                action_type=ActionType.LOOK,
                success=True,
                narrative_context=f"Player looks at '{target}' but nothing specific stands out. Scene: {context.get('description', '')}",
            )

        # General look — build a rich overview
        parts = [f"Player looks around the area."]
        parts.append(f"Scene: {context.get('description', '')}")

        state_changes = context.get("state_changes", [])
        if state_changes:
            parts.append(f"Changes since arrival: {'; '.join(state_changes)}")

        dead = context.get("dead_npcs", [])
        if dead:
            parts.append(f"Dead: {', '.join(dead)}")

        npcs = context.get("npcs", [])
        if npcs:
            parts.append(f"NPCs present: {'; '.join(n['name'] + ' (' + n['disposition'] + '): ' + n['description'] for n in npcs)}")

        items = context.get("items", [])
        if items:
            parts.append(f"Visible items: {', '.join(i['name'] for i in items)}")

        exits = context.get("exits", [])
        if exits:
            parts.append(f"Exits: {'; '.join(e['direction'] + ': ' + e.get('description', '') for e in exits)}")

        if context.get("ai_notes"):
            parts.append(f"[DM Notes: {context['ai_notes']}]")

        return ActionResult(
            action_type=ActionType.LOOK,
            success=True,
            narrative_context="\n".join(parts),
        )

    def _handle_search(self, params: dict) -> ActionResult:
        """Handle searching the current scene."""
        character = self.get_character()
        if not character:
            return ActionResult(action_type=ActionType.SEARCH, success=False, error="No character")

        # Roll Investigation or Perception
        skill = params.get("skill", "investigation")
        ability = SKILL_ABILITIES.get(skill, "intelligence")
        score = getattr(character, ability, 10)
        skills = json.loads(character.skill_proficiencies)
        proficient = skill in skills

        check = ability_check(
            ability_score=score,
            dc=0,  # We check against individual DCs
            proficient=proficient,
            level=character.level,
            skill_name=skill.replace("-", " ").title(),
        )

        # Check what they find
        found = check_search_results(
            self.adventure,
            self.session.current_scene_id,
            self.get_flags(),
            check.roll.total,
        )

        # Set discovered flags for hidden exits
        for item in found:
            if item["type"] == "exit":
                scene = self.adventure.scenes.get(self.session.current_scene_id)
                for exit in scene.exits:
                    if exit.direction == item["direction"]:
                        self.set_flag(f"discovered_{exit.target_scene}")

        return ActionResult(
            action_type=ActionType.SEARCH,
            success=len(found) > 0,
            narrative_context=f"Player searches the area. Rolled {check.roll.total} on {skill}.",
            roll_results=[{
                "type": "skill_check",
                "skill": skill,
                "roll": str(check.roll),
                "total": check.roll.total,
            }],
            items_found=found,
        )

    def _handle_talk(self, params: dict) -> ActionResult:
        """Handle talking to an NPC."""
        npc_name = params.get("npc", "")
        topic = params.get("topic", "")

        # Find NPC in current scene
        scene = self.adventure.scenes.get(self.session.current_scene_id) if self.adventure else None
        if not scene:
            return ActionResult(action_type=ActionType.TALK, success=False, error="No current scene")

        flags = self.get_flags()
        npc_data = None
        matched_npc_id = None
        for npc_id in scene.npcs:
            npc = self.adventure.npcs.get(npc_id)
            if npc and (
                npc_name.lower() in npc.name.lower()
                or npc.name.lower() in npc_name.lower()
                or npc_id.lower() in npc_name.lower()
            ):
                npc_data = npc
                matched_npc_id = npc_id
                break

        if not npc_data:
            return ActionResult(
                action_type=ActionType.TALK,
                success=False,
                narrative_context=f"There's no one called '{npc_name}' here to talk to.",
            )

        # Check if NPC is dead
        if flags.get(f"npc_{matched_npc_id}_dead"):
            return ActionResult(
                action_type=ActionType.TALK,
                success=False,
                narrative_context=f"{npc_data.name} is dead.",
            )

        # Build flag-aware dialogue hints
        base_hints = list(npc_data.dialogue_hints)
        dialogue_by_flag = getattr(npc_data, 'dialogue_by_flag', {})
        for flag_name, hints in dialogue_by_flag.items():
            if flags.get(flag_name):
                base_hints.extend(hints)

        # Build rich context for Claude DM
        context_parts = [
            f"Player talks to {npc_data.name}",
            f"Topic: '{topic}'" if topic else "General conversation",
            f"NPC description: {npc_data.description}",
            f"Disposition: {npc_data.disposition}",
            f"Dialogue hints: {'; '.join(base_hints)}",
            f"NPC knows about: {', '.join(npc_data.knows_about)}" if npc_data.knows_about else "",
        ]
        # Include relevant story flags so Claude can adapt
        relevant_flags = {k: v for k, v in flags.items() if v}
        if relevant_flags:
            context_parts.append(f"Story state: {json.dumps(relevant_flags)}")

        return ActionResult(
            action_type=ActionType.TALK,
            success=True,
            narrative_context="\n".join(p for p in context_parts if p),
        )

    def _handle_attack(self, params: dict) -> ActionResult:
        """Handle attacking a target."""
        target_name = params.get("target", "")
        weapon = params.get("weapon", "")
        character = self.get_character()

        if not character:
            return ActionResult(action_type=ActionType.ATTACK, success=False, error="No character")

        # Find combat entity target
        entities = self.get_combat_entities()
        target = None
        for e in entities:
            if e.name.lower() in target_name.lower() or target_name.lower() in e.name.lower():
                if e.is_alive:
                    target = e
                    break

        if not target:
            return ActionResult(
                action_type=ActionType.ATTACK,
                success=False,
                narrative_context=f"No valid target '{target_name}' to attack.",
            )

        # Calculate attack bonus (simplified: STR for melee, DEX for ranged)
        # TODO: Use actual weapon properties from SRD
        atk_ability = "strength"  # Default melee
        if weapon and ("bow" in weapon.lower() or "ranged" in weapon.lower()):
            atk_ability = "dexterity"

        atk_score = getattr(character, atk_ability, 10)
        atk_mod = ability_modifier(atk_score) + proficiency_bonus(character.level)

        # Default damage (TODO: look up actual weapon)
        damage_dice = params.get("damage_dice", "1d8+{}".format(ability_modifier(atk_score)))

        result = attack_roll(
            attack_bonus=atk_mod,
            target_ac=target.armor_class,
            damage_dice=damage_dice,
            damage_type=params.get("damage_type", "slashing"),
        )

        # Apply damage
        if result.hit:
            target.current_hp -= result.damage
            if target.current_hp <= 0:
                target.current_hp = 0
                target.is_alive = False

        self.db.commit()
        self.db.refresh(target)  # Force re-read so HP is accurate

        # Check if all enemies dead
        alive_enemies = [e for e in self.get_combat_entities() if e.is_alive]
        combat_ended = len(alive_enemies) == 0

        return ActionResult(
            action_type=ActionType.ATTACK,
            success=result.hit,
            narrative_context=(
                f"Player attacks {target.name} with {weapon or 'their weapon'}. "
                f"{'CRITICAL HIT! ' if result.critical else ''}"
                f"{'Hit' if result.hit else 'Miss'}. "
                f"{'Dealt ' + str(result.damage) + ' damage. ' if result.hit else ''}"
                f"{target.name + ' has ' + str(target.current_hp) + ' HP remaining.' if result.hit and target.is_alive else ''}"
                f"{target.name + ' falls!' if not target.is_alive else ''}"
            ),
            roll_results=[{
                "type": "attack",
                "roll": str(result.attack_roll),
                "total": result.attack_roll.total,
                "target_ac": target.armor_class,
                "hit": result.hit,
                "critical": result.critical,
                "damage": result.damage if result.hit else 0,
                "damage_roll": str(result.damage_roll) if result.damage_roll else "",
                "damage_type": result.damage_type,
            }],
            damage_dealt=result.damage if result.hit else 0,
            combat_ended=combat_ended,
        )

    def _handle_skill_check(self, params: dict) -> ActionResult:
        """Handle a generic skill check."""
        skill = params.get("skill", "")
        dc = params.get("dc", 10)
        character = self.get_character()

        if not character:
            return ActionResult(action_type=ActionType.SKILL_CHECK, success=False, error="No character")

        ability = SKILL_ABILITIES.get(skill, "strength")
        score = getattr(character, ability, 10)
        skills = json.loads(character.skill_proficiencies)
        proficient = skill in skills

        check = ability_check(
            ability_score=score,
            dc=dc,
            proficient=proficient,
            level=character.level,
            skill_name=skill.replace("-", " ").title(),
        )

        return ActionResult(
            action_type=ActionType.SKILL_CHECK,
            success=check.success,
            narrative_context=f"Player attempts {skill} check (DC {dc}). Rolled {check.roll.total}. {'Success!' if check.success else 'Failure.'}",
            roll_results=[{
                "type": "skill_check",
                "skill": skill,
                "dc": dc,
                "roll": str(check.roll),
                "total": check.roll.total,
                "success": check.success,
            }],
        )

    def _handle_pick_up(self, params: dict) -> ActionResult:
        """Handle picking up an item."""
        item_name = params.get("item", "")

        return ActionResult(
            action_type=ActionType.PICK_UP,
            success=True,
            narrative_context=f"Player picks up {item_name}.",
            state_changes=[f"Added {item_name} to inventory"],
        )

    def _handle_rest(self, params: dict) -> ActionResult:
        """Handle short or long rest."""
        rest_type = params.get("type", "short")
        character = self.get_character()
        scene_ctx = self.get_current_scene_context()

        if not scene_ctx.get("rest_allowed", True):
            return ActionResult(
                action_type=ActionType.REST,
                success=False,
                narrative_context="This doesn't seem like a safe place to rest.",
            )

        if character and rest_type == "long":
            character.current_hp = character.max_hp
            character.hit_dice_remaining = character.level
            # Reset spell slots
            character.spell_slots_current = character.spell_slots_max
            self.db.commit()

        elif character and rest_type == "short":
            # Short rest: can spend hit dice
            if character.hit_dice_remaining > 0:
                # TODO: actually roll hit dice
                heal = max(1, roll_dice(f"1d{8}").total + ability_modifier(character.constitution))
                character.current_hp = min(character.max_hp, character.current_hp + heal)
                character.hit_dice_remaining -= 1
                self.db.commit()

        return ActionResult(
            action_type=ActionType.REST,
            success=True,
            narrative_context=f"Player takes a {rest_type} rest. {'HP fully restored.' if rest_type == 'long' else 'Spent a hit die to heal.'}",
        )

    def _handle_free_action(self, params: dict) -> ActionResult:
        """Handle freeform actions - let the AI interpret with full context."""
        action_text = params.get("text", "")
        context = self.get_current_scene_context()
        character = self.get_character()

        # Build rich context so the DM can decide what mechanics apply
        parts = [f'Player says/does: "{action_text}"']
        parts.append(f"Current scene: {context.get('name', '?')} — {context.get('scene_type', 'exploration')}")

        if self.session.in_combat:
            parts.append("Currently in combat!")

        npcs = context.get("npcs", [])
        if npcs:
            parts.append(f"NPCs present: {', '.join(n['name'] for n in npcs)}")

        items = context.get("items", [])
        if items:
            parts.append(f"Items available: {', '.join(i['name'] for i in items)}")

        if character:
            skills = json.loads(character.skill_proficiencies)
            parts.append(f"Character skills: {', '.join(skills)}")

        parts.append(
            "NOTE: This free action has no mechanical resolution. "
            "If this action requires a dice roll, use skill_check or attack instead. "
            "The DM should narrate the attempt and suggest the appropriate follow-up tool call."
        )

        return ActionResult(
            action_type=ActionType.FREE_ACTION,
            success=True,
            narrative_context="\n".join(parts),
        )

    def _handle_end_turn(self, params: dict) -> ActionResult:
        """Handle ending a combat turn — triggers monster turns."""
        if self.session.in_combat:
            return self._process_monster_turns()
        return ActionResult(
            action_type=ActionType.END_TURN,
            success=True,
            narrative_context="Player ends their turn.",
        )

    def _process_monster_turns(self) -> ActionResult:
        """Process all living monster attacks against the player."""
        character = self.get_character()
        if not character:
            return ActionResult(action_type=ActionType.END_TURN, success=True)

        entities = self.get_combat_entities()
        alive_enemies = [e for e in entities if e.is_alive and e.entity_type == "monster"]

        if not alive_enemies:
            return ActionResult(
                action_type=ActionType.END_TURN,
                success=True,
                combat_ended=True,
                narrative_context="All enemies have been defeated!",
            )

        monster_attacks = []
        total_damage_taken = 0

        for enemy in alive_enemies:
            stat_block = json.loads(enemy.stat_block) if enemy.stat_block else {}
            actions = stat_block.get("actions", [])

            # Pick the first attack action
            attack_action = None
            for action in actions:
                if action.get("attack_bonus") is not None:
                    attack_action = action
                    break

            if not attack_action:
                monster_attacks.append({
                    "attacker": enemy.name,
                    "action": "No attack available",
                    "hit": False,
                    "damage": 0,
                })
                continue

            # Roll the attack
            atk_bonus = attack_action.get("attack_bonus", 0)
            damage_entries = attack_action.get("damage", [])
            damage_dice = "1d4"
            damage_type = "bludgeoning"
            if damage_entries:
                damage_dice = damage_entries[0].get("damage_dice", "1d4")
                dt = damage_entries[0].get("damage_type", {})
                damage_type = dt.get("name", "bludgeoning") if isinstance(dt, dict) else "bludgeoning"

            result = attack_roll(
                attack_bonus=atk_bonus,
                target_ac=character.armor_class,
                damage_dice=damage_dice,
                damage_type=damage_type,
            )

            attack_info = {
                "attacker": enemy.name,
                "action": attack_action.get("name", "Attack"),
                "roll": str(result.attack_roll),
                "total": result.attack_roll.total,
                "target_ac": character.armor_class,
                "hit": result.hit,
                "critical": result.critical,
                "damage": result.damage if result.hit else 0,
                "damage_type": damage_type,
            }

            if result.hit:
                character.current_hp -= result.damage
                total_damage_taken += result.damage
                if character.current_hp <= 0:
                    character.current_hp = 0
                    character.is_alive = False

            monster_attacks.append(attack_info)

        self.db.commit()
        self.db.refresh(character)  # Force re-read so HP is accurate

        # Build narrative context
        attack_narratives = []
        for atk in monster_attacks:
            if atk["hit"]:
                crit = " CRITICAL HIT!" if atk.get("critical") else ""
                attack_narratives.append(
                    f"{atk['attacker']} attacks with {atk['action']}: "
                    f"rolled {atk.get('roll', '?')} vs AC {atk.get('target_ac', '?')} — HIT!{crit} "
                    f"Deals {atk['damage']} {atk.get('damage_type', '')} damage."
                )
            else:
                attack_narratives.append(
                    f"{atk['attacker']} attacks with {atk['action']}: "
                    f"rolled {atk.get('roll', '?')} vs AC {atk.get('target_ac', '?')} — MISS!"
                )

        if not character.is_alive:
            attack_narratives.append(f"{character.name} falls unconscious! (0 HP)")

        narrative = "MONSTER TURNS:\n" + "\n".join(attack_narratives)
        narrative += f"\n{character.name} HP: {character.current_hp}/{character.max_hp}"

        return ActionResult(
            action_type=ActionType.END_TURN,
            success=True,
            narrative_context=narrative,
            roll_results=[{
                "type": "monster_attack",
                **atk,
            } for atk in monster_attacks],
            damage_taken=total_damage_taken,
        )

    # ------------------------------------------------------------------
    # Combat Management
    # ------------------------------------------------------------------

    def start_combat(self, encounter_id: str) -> dict:
        """Initialize combat from an encounter definition."""
        if not self.adventure:
            return {"error": "No adventure loaded"}

        scene = self.adventure.scenes.get(self.session.current_scene_id)
        if not scene:
            return {"error": "No current scene"}

        # Find the encounter
        encounter = None
        for enc in scene.encounters:
            if enc.id == encounter_id:
                encounter = enc
                break

        if not encounter:
            return {"error": f"Encounter '{encounter_id}' not found"}

        # Spawn monsters
        spawned = []
        for monster_def in encounter.monsters:
            srd_monster = get_srd_entry(DB_PATH, "monsters", monster_def.srd_index)
            if not srd_monster:
                continue

            for i in range(monster_def.count):
                name = monster_def.name_override or srd_monster["name"]
                if monster_def.count > 1 and not monster_def.name_override:
                    name = f"{name} {i + 1}"

                hp = monster_def.hp_override or srd_monster["hit_points"]
                ac = srd_monster["armor_class"][0]["value"]

                entity = CombatEntity(
                    session_id=self.session_id,
                    name=name,
                    monster_index=monster_def.srd_index,
                    entity_type="monster",
                    max_hp=hp,
                    current_hp=hp,
                    armor_class=ac,
                    initiative=roll_initiative(srd_monster.get("dexterity", 10)).total,
                    stat_block=json.dumps(srd_monster),
                    is_alive=True,
                    is_active=True,
                )
                self.db.add(entity)
                spawned.append({"name": name, "hp": hp, "ac": ac, "initiative": entity.initiative})

        # Roll player initiative
        character = self.get_character()
        player_init = roll_initiative(character.dexterity).total if character else 10

        # Set session to combat mode
        self.session.in_combat = True

        # Build initiative order
        all_combatants = [{"name": character.name, "initiative": player_init, "is_player": True}]
        for s in spawned:
            all_combatants.append({"name": s["name"], "initiative": s["initiative"], "is_player": False})
        all_combatants.sort(key=lambda x: x["initiative"], reverse=True)
        self.session.initiative_order = json.dumps(all_combatants)

        self.db.commit()

        return {
            "encounter_id": encounter_id,
            "description": encounter.description,
            "monsters_spawned": spawned,
            "initiative_order": all_combatants,
            "player_initiative": player_init,
        }

    def end_combat(self, encounter_id: str) -> dict:
        """End combat and clean up."""
        # Mark all combat entities as inactive
        entities = self.get_combat_entities()
        for e in entities:
            e.is_active = False
        self.session.in_combat = False
        self.session.initiative_order = "[]"

        # Set encounter completion flag
        self.set_flag(f"encounter_{encounter_id}_complete")

        # Find encounter for XP/loot
        scene = self.adventure.scenes.get(self.session.current_scene_id) if self.adventure else None
        xp_reward = 0
        loot = []
        encounter_flag = ""
        if scene:
            for enc in scene.encounters:
                if enc.id == encounter_id:
                    xp_reward = enc.xp_reward
                    loot = enc.loot
                    encounter_flag = enc.sets_flag
                    break

        if encounter_flag:
            self.set_flag(encounter_flag)

        # Mark encounter NPCs as dead
        # Check which NPCs in this scene are linked to encounter monsters
        if scene:
            for enc in scene.encounters:
                if enc.id == encounter_id:
                    # Mark NPCs killed by this encounter
                    npcs_killed = getattr(enc, 'npcs_killed', [])
                    for npc_id in npcs_killed:
                        self.set_flag(f"npc_{npc_id}_dead")
                    break

        # Award XP
        character = self.get_character()
        if character and xp_reward:
            character.xp += xp_reward

        self.db.commit()

        return {
            "encounter_id": encounter_id,
            "xp_awarded": xp_reward,
            "loot": loot,
            "encounter_flag": encounter_flag,
        }

    # ------------------------------------------------------------------
    # AI Context Building
    # ------------------------------------------------------------------

    def build_ai_context(self, action_result: ActionResult | None = None) -> dict:
        """
        Build the complete context packet for the AI narrator.
        This is THE critical function — it determines everything the AI knows.
        """
        character = self.get_character()
        scene_ctx = self.get_current_scene_context()
        flags = self.get_flags()

        # Get recent narrative history (last 10 entries)
        recent_log = (
            self.db.query(NarrativeLog)
            .filter_by(session_id=self.session_id)
            .order_by(NarrativeLog.id.desc())
            .limit(10)
            .all()
        )
        recent_log.reverse()  # Chronological order
        history = [{"source": l.source, "type": l.entry_type, "content": l.content} for l in recent_log]

        context = {
            "adventure_name": self.adventure.name if self.adventure else "Unknown",
            "scene": scene_ctx,
            "character": character.to_game_state() if character else {},
            "in_combat": self.session.in_combat if self.session else False,
            "story_flags": flags,
            "recent_history": history,
        }

        # Add combat state if in combat
        if self.session and self.session.in_combat:
            entities = self.get_combat_entities()
            context["combat"] = {
                "initiative_order": json.loads(self.session.initiative_order or "[]"),
                "enemies": [
                    {
                        "name": e.name,
                        "hp": f"{e.current_hp}/{e.max_hp}",
                        "alive": e.is_alive,
                        "ac": e.armor_class,
                    }
                    for e in entities
                ],
            }

        # Add action result if present
        if action_result:
            context["last_action"] = {
                "type": action_result.action_type.value,
                "success": action_result.success,
                "narrative_context": action_result.narrative_context,
                "rolls": action_result.roll_results,
                "items_found": action_result.items_found,
                "damage_dealt": action_result.damage_dealt,
                "combat_started": action_result.combat_started,
                "combat_ended": action_result.combat_ended,
            }

        return context

    # ------------------------------------------------------------------
    # Narrative Logging
    # ------------------------------------------------------------------

    def _log_action(self, action_type: ActionType, params: dict, result: ActionResult):
        """Log an action to the narrative log."""
        character = self.get_character()
        entry = NarrativeLog(
            session_id=self.session_id,
            source="player",
            character_id=character.id if character else None,
            entry_type=action_type.value,
            content=result.narrative_context,
            metadata_json=json.dumps({
                "params": params,
                "rolls": result.roll_results,
                "success": result.success,
            }),
        )
        self.db.add(entry)
        self.db.commit()

    def log_ai_narrative(self, content: str, entry_type: str = "narrative"):
        """Log an AI-generated narrative entry."""
        entry = NarrativeLog(
            session_id=self.session_id,
            source="ai",
            entry_type=entry_type,
            content=content,
        )
        self.db.add(entry)
        self.db.commit()

    def log_system(self, content: str):
        """Log a system message."""
        entry = NarrativeLog(
            session_id=self.session_id,
            source="system",
            entry_type="system",
            content=content,
        )
        self.db.add(entry)
        self.db.commit()


# ------------------------------------------------------------------
# Session Creation Helper
# ------------------------------------------------------------------

def create_game_session(
    character_id: int,
    adventure_file: str,
    session_name: str = "",
) -> GameSession:
    """Create a new game session with a character and adventure."""
    db = get_session(DB_PATH)

    # Load adventure to get metadata
    adventure = load_adventure(adventure_file)

    session = GameSession(
        name=session_name or adventure.name,
        adventure_id=adventure.id,
        state="active",
        current_scene_id=adventure.starting_scene,
        story_flags="{}",
    )
    db.add(session)
    db.flush()

    # Add participant
    participant = SessionParticipant(
        session_id=session.id,
        character_id=character_id,
    )
    db.add(participant)
    db.commit()

    session_id = session.id
    db.close()

    # Re-fetch in a clean session so callers can use it
    db2 = get_session(DB_PATH)
    return db2.query(GameSession).get(session_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/home/claude/ai-dungeon-master")

    from src.engine.character_creation import build_character
    from src.models.database import User, init_db

    print("=== Game Session Engine Test ===\n")

    init_db()

    db = get_session(DB_PATH)

    # Create a test user
    user = db.query(User).filter_by(username="testplayer").first()
    if not user:
        user = User(username="testplayer", display_name="Test Player", password_hash="test")
        db.add(user)
        db.commit()

    # Create a test character
    char = build_character(
        user_id=user.id,
        name="Kira Shadowstep",
        race="elf",
        char_class="rogue",
        ability_scores={"str": 10, "dex": 16, "con": 12, "int": 14, "wis": 13, "cha": 8},
        skill_choices=["stealth", "perception", "investigation", "sleight-of-hand"],
        alignment="chaotic-good",
    )
    db.add(char)
    db.commit()
    print(f"Created character: {char.name} (Elf Rogue, HP: {char.current_hp})")

    # Create a game session
    session = create_game_session(
        character_id=char.id,
        adventure_file="adventures/goblin_cave.json",
    )
    print(f"Created session: {session.name} (ID: {session.id})")
    print(f"Starting scene: {session.current_scene_id}")

    # Initialize engine
    engine = GameEngine(session.id)

    # Get initial scene context
    ctx = engine.get_current_scene_context()
    print(f"\nScene: {ctx['name']}")
    print(f"NPCs: {[n['name'] for n in ctx['npcs']]}")
    print(f"Exits: {[e['direction'] for e in ctx['exits']]}")

    # Simulate some actions
    print("\n--- Player talks to Bram ---")
    result = engine.process_action("talk", {"npc": "Bram", "topic": "the goblin raids"})
    print(f"Success: {result.success}")
    print(f"Context: {result.narrative_context[:200]}...")

    print("\n--- Player moves to the Old Road ---")
    result = engine.process_action("move", {"direction": "outside"})
    print(f"Moved: {result.scene_changed}, New scene: {result.new_scene_id}")

    print("\n--- Player moves to Cave Entrance ---")
    result = engine.process_action("move", {"direction": "trail"})
    print(f"Moved: {result.scene_changed}, New scene: {result.new_scene_id}")

    print("\n--- Player searches the area ---")
    result = engine.process_action("search", {"skill": "perception"})
    print(f"Roll: {result.roll_results}")
    print(f"Found: {result.items_found}")

    print("\n--- Starting combat (lookout fight) ---")
    combat = engine.start_combat("lookout_fight")
    print(f"Monsters: {combat['monsters_spawned']}")
    print(f"Initiative: {combat['initiative_order']}")

    print("\n--- Player attacks ---")
    result = engine.process_action("attack", {
        "target": "Snik",
        "weapon": "shortsword",
        "damage_dice": "1d6+3",
    })
    print(f"Result: {result.narrative_context}")

    print("\n--- Full AI Context ---")
    ai_ctx = engine.build_ai_context(result)
    print(f"Scene: {ai_ctx['scene']['name']}")
    print(f"In combat: {ai_ctx['in_combat']}")
    print(f"Character HP: {ai_ctx['character']['hp']}")
    if ai_ctx.get('combat'):
        print(f"Enemies: {ai_ctx['combat']['enemies']}")
    print(f"History entries: {len(ai_ctx['recent_history'])}")
