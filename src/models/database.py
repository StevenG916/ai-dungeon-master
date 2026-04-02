"""
Database Models
Characters, game sessions, and game state.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# User / Auth (minimal for now)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt later
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    characters = relationship("Character", back_populates="user")


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)

    # Core identity
    race = Column(String(50), nullable=False)          # e.g. "elf"
    subrace = Column(String(50), nullable=True)         # e.g. "high-elf"
    char_class = Column(String(50), nullable=False)     # e.g. "wizard"
    subclass = Column(String(50), nullable=True)
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    alignment = Column(String(30), default="neutral")
    background = Column(String(50), default="acolyte")

    # Ability scores
    strength = Column(Integer, nullable=False)
    dexterity = Column(Integer, nullable=False)
    constitution = Column(Integer, nullable=False)
    intelligence = Column(Integer, nullable=False)
    wisdom = Column(Integer, nullable=False)
    charisma = Column(Integer, nullable=False)

    # Combat stats
    max_hp = Column(Integer, nullable=False)
    current_hp = Column(Integer, nullable=False)
    temp_hp = Column(Integer, default=0)
    armor_class = Column(Integer, default=10)
    speed = Column(Integer, default=30)

    # Resources
    hit_dice_remaining = Column(Integer, default=1)

    # Spell slots (JSON: {"1": 2, "2": 1} etc)
    spell_slots_max = Column(Text, default="{}")
    spell_slots_current = Column(Text, default="{}")

    # Proficiencies, skills, languages stored as JSON arrays
    proficiencies = Column(Text, default="[]")       # ["light-armor", "simple-weapons"]
    skill_proficiencies = Column(Text, default="[]") # ["perception", "stealth"]
    languages = Column(Text, default="[]")           # ["common", "elvish"]
    saving_throw_proficiencies = Column(Text, default="[]")  # ["dex", "int"]

    # Equipment & inventory (JSON)
    equipment = Column(Text, default="[]")
    # e.g. [{"index": "longsword", "name": "Longsword", "quantity": 1, "equipped": true}]

    # Spells known/prepared (JSON)
    spells_known = Column(Text, default="[]")   # ["fire-bolt", "magic-missile"]
    spells_prepared = Column(Text, default="[]")

    # Features and traits (JSON)
    features = Column(Text, default="[]")
    traits = Column(Text, default="[]")

    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_alive = Column(Boolean, default=True)

    user = relationship("User", back_populates="characters")

    # ---- Helper properties ----

    def get_ability_modifier(self, ability: str) -> int:
        score = getattr(self, ability, 10)
        return (score - 10) // 2

    def get_proficiency_bonus(self) -> int:
        return (self.level - 1) // 4 + 2

    def get_skill_modifier(self, skill: str, ability: str) -> int:
        mod = self.get_ability_modifier(ability)
        skills = json.loads(self.skill_proficiencies)
        if skill in skills:
            mod += self.get_proficiency_bonus()
        return mod

    def is_proficient_save(self, ability: str) -> bool:
        saves = json.loads(self.saving_throw_proficiencies)
        return ability in saves

    def get_save_modifier(self, ability: str) -> int:
        mod = self.get_ability_modifier(ability)
        if self.is_proficient_save(ability):
            mod += self.get_proficiency_bonus()
        return mod

    def to_game_state(self) -> dict:
        """Export character state for AI context injection."""
        return {
            "name": self.name,
            "race": self.race,
            "class": self.char_class,
            "level": self.level,
            "hp": f"{self.current_hp}/{self.max_hp}",
            "ac": self.armor_class,
            "abilities": {
                "STR": self.strength,
                "DEX": self.dexterity,
                "CON": self.constitution,
                "INT": self.intelligence,
                "WIS": self.wisdom,
                "CHA": self.charisma,
            },
            "equipment": json.loads(self.equipment),
            "spells_known": json.loads(self.spells_known),
            "conditions": [],  # TODO: track active conditions
        }


# ---------------------------------------------------------------------------
# Game Session
# ---------------------------------------------------------------------------
class GameSession(Base):
    __tablename__ = "game_sessions"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    adventure_id = Column(String(100), nullable=True)  # Reference to adventure module
    state = Column(String(20), default="active")  # active, paused, completed

    # Current location in the adventure
    current_scene_id = Column(String(100), nullable=True)
    story_flags = Column(Text, default="{}")  # JSON: {"talked_to_innkeeper": true, ...}

    # Turn management
    current_turn = Column(Integer, default=0)
    in_combat = Column(Boolean, default=False)
    initiative_order = Column(Text, default="[]")  # JSON array of combatant order

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    participants = relationship("SessionParticipant", back_populates="session")
    log_entries = relationship("NarrativeLog", back_populates="session", order_by="NarrativeLog.id")
    combat_entities = relationship("CombatEntity", back_populates="session")

    def get_flags(self) -> dict:
        return json.loads(self.story_flags)

    def set_flag(self, key: str, value) -> None:
        flags = self.get_flags()
        flags[key] = value
        self.story_flags = json.dumps(flags)


class SessionParticipant(Base):
    __tablename__ = "session_participants"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("GameSession", back_populates="participants")
    character = relationship("Character")


# ---------------------------------------------------------------------------
# Narrative Log - the scrolling story
# ---------------------------------------------------------------------------
class NarrativeLog(Base):
    __tablename__ = "narrative_log"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)

    # Who generated this entry
    source = Column(String(20), nullable=False)  # "ai", "system", "player"
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)

    # Content
    entry_type = Column(String(30), nullable=False)
    # Types: "narrative", "dialogue", "action", "roll_result",
    #        "combat", "system", "scene_change"
    content = Column(Text, nullable=False)

    # Optional structured data (roll results, combat details, etc.)
    metadata_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("GameSession", back_populates="log_entries")


# ---------------------------------------------------------------------------
# Combat tracking
# ---------------------------------------------------------------------------
class CombatEntity(Base):
    """Tracks monsters and NPCs in active combat."""
    __tablename__ = "combat_entities"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)

    # Identity
    name = Column(String(100), nullable=False)  # "Goblin 1", "Goblin 2"
    monster_index = Column(String(100), nullable=True)  # SRD index key
    entity_type = Column(String(20), default="monster")  # monster, npc, ally

    # Combat stats (copied from SRD at spawn time)
    max_hp = Column(Integer, nullable=False)
    current_hp = Column(Integer, nullable=False)
    armor_class = Column(Integer, nullable=False)
    initiative = Column(Integer, default=0)

    # Full stat block (JSON - copied from SRD for quick reference)
    stat_block = Column(Text, default="{}")

    is_alive = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)  # Still in this combat?

    session = relationship("GameSession", back_populates="combat_entities")


# ---------------------------------------------------------------------------
# Adventure Module Schema
# ---------------------------------------------------------------------------
class Adventure(Base):
    """A stored adventure module."""
    __tablename__ = "adventures"

    id = Column(String(100), primary_key=True)  # e.g. "goblin-cave-v1"
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    author = Column(String(100), default="")
    version = Column(String(20), default="1.0")

    # The full adventure data (JSON) - scenes, NPCs, encounters, items
    adventure_data = Column(Text, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------
DB_PATH = "game.db"


def get_engine(db_path: str = DB_PATH):
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(db_path: str = DB_PATH):
    """Create all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(db_path: str = DB_PATH) -> Session:
    engine = get_engine(db_path)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


if __name__ == "__main__":
    print("Initializing database tables...")
    init_db()
    print("Done! Tables created.")

    # List tables
    engine = get_engine()
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nTables: {tables}")
