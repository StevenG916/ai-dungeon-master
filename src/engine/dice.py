"""
Dice Roller & Core Rules Engine
Handles all mechanical resolution - the AI never touches dice or math.
"""

import random
import re
from dataclasses import dataclass


@dataclass
class RollResult:
    """Result of a dice roll with full breakdown."""
    expression: str      # Original expression like "2d6+3"
    rolls: list[int]     # Individual die results
    modifier: int        # Static modifier
    total: int           # Final total
    natural: int | None  # Natural d20 roll (for crit/fumble detection)
    critical: bool = False
    fumble: bool = False

    def __str__(self):
        if len(self.rolls) == 1 and self.modifier == 0:
            return f"[{self.rolls[0]}] = {self.total}"
        parts = f"[{', '.join(str(r) for r in self.rolls)}]"
        if self.modifier > 0:
            parts += f" + {self.modifier}"
        elif self.modifier < 0:
            parts += f" - {abs(self.modifier)}"
        return f"{parts} = {self.total}"


def roll_dice(expression: str) -> RollResult:
    """
    Roll dice from a standard notation string.
    Supports: d20, 2d6, 1d8+3, 2d6-1, d20+5
    """
    expression = expression.strip().lower()

    # Parse the expression: NdS+M or NdS-M
    match = re.match(r'^(\d*)d(\d+)([+-]\d+)?$', expression)
    if not match:
        raise ValueError(f"Invalid dice expression: {expression}")

    num_dice = int(match.group(1)) if match.group(1) else 1
    die_size = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    rolls = [random.randint(1, die_size) for _ in range(num_dice)]
    total = sum(rolls) + modifier

    # Check for natural 20/1 on d20 rolls
    natural = rolls[0] if die_size == 20 and num_dice == 1 else None
    critical = natural == 20 if natural is not None else False
    fumble = natural == 1 if natural is not None else False

    return RollResult(
        expression=expression,
        rolls=rolls,
        modifier=modifier,
        total=total,
        natural=natural,
        critical=critical,
        fumble=fumble,
    )


def roll_d20(modifier: int = 0, advantage: bool = False, disadvantage: bool = False) -> RollResult:
    """Roll a d20 with optional advantage/disadvantage."""
    if advantage and disadvantage:
        # They cancel out
        advantage = False
        disadvantage = False

    if advantage:
        r1 = random.randint(1, 20)
        r2 = random.randint(1, 20)
        natural = max(r1, r2)
        rolls = [r1, r2]
    elif disadvantage:
        r1 = random.randint(1, 20)
        r2 = random.randint(1, 20)
        natural = min(r1, r2)
        rolls = [r1, r2]
    else:
        natural = random.randint(1, 20)
        rolls = [natural]

    total = natural + modifier

    return RollResult(
        expression=f"d20{'+' if modifier >= 0 else ''}{modifier}" if modifier else "d20",
        rolls=rolls,
        modifier=modifier,
        total=total,
        natural=natural,
        critical=(natural == 20),
        fumble=(natural == 1),
    )


def ability_modifier(score: int) -> int:
    """Calculate ability modifier from ability score."""
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    """Calculate proficiency bonus from character level."""
    return (level - 1) // 4 + 2


@dataclass
class AbilityCheck:
    """Result of an ability check or saving throw."""
    roll: RollResult
    dc: int
    success: bool
    skill_name: str = ""

    def __str__(self):
        result = "SUCCESS" if self.success else "FAILURE"
        return f"{self.skill_name + ': ' if self.skill_name else ''}{self.roll} vs DC {self.dc} - {result}"


def ability_check(
    ability_score: int,
    dc: int,
    proficient: bool = False,
    level: int = 1,
    advantage: bool = False,
    disadvantage: bool = False,
    skill_name: str = "",
) -> AbilityCheck:
    """Perform an ability check against a DC."""
    mod = ability_modifier(ability_score)
    if proficient:
        mod += proficiency_bonus(level)

    roll = roll_d20(modifier=mod, advantage=advantage, disadvantage=disadvantage)

    # Natural 20 always succeeds on attack rolls (not ability checks in RAW,
    # but many tables play this way - can be toggled later)
    success = roll.total >= dc

    return AbilityCheck(roll=roll, dc=dc, success=success, skill_name=skill_name)


@dataclass
class AttackResult:
    """Result of an attack roll and damage."""
    attack_roll: RollResult
    target_ac: int
    hit: bool
    critical: bool
    damage: int
    damage_roll: RollResult | None
    damage_type: str

    def __str__(self):
        if not self.hit:
            if self.attack_roll.fumble:
                return f"FUMBLE! {self.attack_roll} vs AC {self.target_ac} - Critical Miss!"
            return f"MISS: {self.attack_roll} vs AC {self.target_ac}"
        if self.critical:
            return f"CRITICAL HIT! {self.attack_roll} vs AC {self.target_ac} - {self.damage} {self.damage_type} damage! {self.damage_roll}"
        return f"HIT: {self.attack_roll} vs AC {self.target_ac} - {self.damage} {self.damage_type} damage {self.damage_roll}"


def attack_roll(
    attack_bonus: int,
    target_ac: int,
    damage_dice: str,
    damage_type: str = "slashing",
    advantage: bool = False,
    disadvantage: bool = False,
) -> AttackResult:
    """Perform an attack roll, check for hit, and roll damage if hit."""
    roll = roll_d20(modifier=attack_bonus, advantage=advantage, disadvantage=disadvantage)

    # Natural 20 always hits, natural 1 always misses
    if roll.critical:
        hit = True
    elif roll.fumble:
        hit = False
    else:
        hit = roll.total >= target_ac

    damage = 0
    damage_roll_result = None

    if hit:
        damage_roll_result = roll_dice(damage_dice)
        damage = damage_roll_result.total

        # Critical hit: roll damage dice twice
        if roll.critical:
            crit_extra = roll_dice(damage_dice)
            # Add only the dice, not the modifier again
            damage += sum(crit_extra.rolls)
            damage_roll_result = RollResult(
                expression=f"{damage_dice} (crit)",
                rolls=damage_roll_result.rolls + crit_extra.rolls,
                modifier=damage_roll_result.modifier,
                total=damage,
                natural=None,
            )

    return AttackResult(
        attack_roll=roll,
        target_ac=target_ac,
        hit=hit,
        critical=roll.critical,
        damage=max(0, damage),  # Damage can't be negative
        damage_roll=damage_roll_result,
        damage_type=damage_type,
    )


def roll_ability_scores() -> list[int]:
    """Roll ability scores using the standard 4d6-drop-lowest method."""
    scores = []
    for _ in range(6):
        rolls = [random.randint(1, 6) for _ in range(4)]
        rolls.sort(reverse=True)
        scores.append(sum(rolls[:3]))  # Drop lowest
    return scores


def standard_array() -> list[int]:
    """Return the standard array for ability scores."""
    return [15, 14, 13, 12, 10, 8]


# Initiative
def roll_initiative(dex_score: int) -> RollResult:
    """Roll initiative (d20 + DEX modifier)."""
    return roll_d20(modifier=ability_modifier(dex_score))


# Hit points
def roll_hit_points(hit_die: int, con_score: int, level: int) -> int:
    """
    Calculate hit points for a character.
    Level 1: max hit die + CON modifier
    Higher levels: roll hit die + CON modifier per level
    """
    con_mod = ability_modifier(con_score)
    hp = hit_die + con_mod  # Level 1 is always max

    for _ in range(level - 1):
        roll = random.randint(1, hit_die)
        hp += max(1, roll + con_mod)  # Minimum 1 HP per level

    return max(1, hp)


if __name__ == "__main__":
    print("=== Dice Engine Tests ===\n")

    print("Roll 2d6+3:", roll_dice("2d6+3"))
    print("Roll d20:", roll_dice("d20"))
    print("Roll 1d8+2:", roll_dice("1d8+2"))

    print("\n=== d20 with advantage ===")
    r = roll_d20(modifier=5, advantage=True)
    print(f"  Rolls: {r.rolls}, Used: {r.natural}, Total: {r.total}")

    print("\n=== Ability Scores (4d6 drop lowest) ===")
    scores = roll_ability_scores()
    print(f"  Scores: {scores}")
    print(f"  Modifiers: {[ability_modifier(s) for s in scores]}")

    print("\n=== Attack Roll ===")
    result = attack_roll(attack_bonus=4, target_ac=15, damage_dice="1d6+2", damage_type="slashing")
    print(f"  {result}")

    print("\n=== Ability Check ===")
    check = ability_check(ability_score=16, dc=15, proficient=True, level=3, skill_name="Perception")
    print(f"  {check}")

    print("\n=== Initiative ===")
    init = roll_initiative(dex_score=14)
    print(f"  Initiative: {init}")
