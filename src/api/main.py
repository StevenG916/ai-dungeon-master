"""
AI Dungeon Master - FastAPI Application
Main entry point for the web application.
"""

import json
import glob
import os
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.data.srd_loader import get_srd_entry, get_srd_list, init_srd_db, search_srd
from src.engine.adventure import load_adventure
from src.engine.character_creation import (
    build_character,
    get_available_classes,
    get_available_races,
    get_class_skill_choices,
)
from src.engine.dice import roll_ability_scores, standard_array
from src.engine.game_session import GameEngine, create_game_session
from src.engine.narrator import generate_narrative
from src.models.database import (
    Character,
    GameSession,
    NarrativeLog,
    User,
    get_session,
    init_db,
)

DB_PATH = "game.db"


@asynccontextmanager
async def lifespan(app):
    """Initialize DB and SRD data on startup."""
    init_db(DB_PATH)
    init_srd_db(DB_PATH)
    yield


app = FastAPI(title="AI Dungeon Master", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# =========================================================================
# Page Routes
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# =========================================================================
# SRD Data API
# =========================================================================

@app.get("/api/srd/{data_type}")
async def list_srd(data_type: str, search: str = ""):
    if search:
        return search_srd(DB_PATH, data_type, search)
    return get_srd_list(DB_PATH, data_type)

@app.get("/api/srd/{data_type}/{index_key}")
async def get_srd(data_type: str, index_key: str):
    entry = get_srd_entry(DB_PATH, data_type, index_key)
    if not entry:
        raise HTTPException(status_code=404, detail="SRD entry not found")
    return entry


# =========================================================================
# Character Creation API
# =========================================================================

@app.get("/api/races")
async def list_races():
    return get_available_races()

@app.get("/api/classes")
async def list_classes():
    return get_available_classes()

@app.get("/api/classes/{class_index}/skills")
async def class_skills(class_index: str):
    return get_class_skill_choices(class_index)

@app.get("/api/ability-scores/roll")
async def roll_scores():
    scores = roll_ability_scores()
    return {"scores": scores, "method": "4d6_drop_lowest"}

@app.get("/api/ability-scores/standard")
async def standard_scores():
    return {"scores": standard_array(), "method": "standard_array"}


class CreateCharacterRequest(BaseModel):
    name: str
    race: str
    char_class: str
    ability_scores: dict  # {"str": 15, "dex": 14, ...}
    skill_choices: list[str]
    subrace: str | None = None
    alignment: str = "neutral"


@app.post("/api/characters")
async def create_character(req: CreateCharacterRequest):
    db = get_session(DB_PATH)
    try:
        # Get or create a default user (simplified for now)
        user = db.query(User).filter_by(username="player1").first()
        if not user:
            user = User(username="player1", display_name="Player 1", password_hash="temp")
            db.add(user)
            db.commit()

        char = build_character(
            user_id=user.id,
            name=req.name,
            race=req.race,
            char_class=req.char_class,
            ability_scores=req.ability_scores,
            skill_choices=req.skill_choices,
            subrace=req.subrace,
            alignment=req.alignment,
        )
        db.add(char)
        db.commit()

        return {
            "id": char.id,
            "name": char.name,
            "race": char.race,
            "class": char.char_class,
            "level": char.level,
            "hp": char.max_hp,
            "ac": char.armor_class,
            "abilities": {
                "STR": char.strength,
                "DEX": char.dexterity,
                "CON": char.constitution,
                "INT": char.intelligence,
                "WIS": char.wisdom,
                "CHA": char.charisma,
            },
        }
    finally:
        db.close()


@app.get("/api/characters")
async def list_characters():
    db = get_session(DB_PATH)
    try:
        chars = db.query(Character).filter_by(is_alive=True).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "race": c.race,
                "class": c.char_class,
                "level": c.level,
                "hp": f"{c.current_hp}/{c.max_hp}",
            }
            for c in chars
        ]
    finally:
        db.close()


# =========================================================================
# Game Session API
# =========================================================================

@app.get("/api/adventures")
async def list_adventures():
    """List available adventure modules."""
    adventures = []
    for f in glob.glob("adventures/*.json"):
        try:
            adv = load_adventure(f)
            adventures.append({
                "id": adv.id,
                "name": adv.name,
                "description": adv.description,
                "level_range": adv.level_range,
                "author": adv.author,
            })
        except Exception:
            pass
    return adventures


class StartSessionRequest(BaseModel):
    character_id: int
    adventure_id: str


@app.post("/api/sessions")
async def start_session(req: StartSessionRequest):
    """Start a new game session."""
    # Find adventure file
    adv_file = None
    for f in glob.glob("adventures/*.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
            if data.get("id") == req.adventure_id:
                adv_file = f
                break
        except Exception:
            pass

    if not adv_file:
        raise HTTPException(status_code=404, detail="Adventure not found")

    session = create_game_session(
        character_id=req.character_id,
        adventure_file=adv_file,
    )

    # Generate opening narrative
    engine = GameEngine(session.id)
    ai_context = engine.build_ai_context()
    adventure = load_adventure(adv_file)
    ai_context["adventure_intro"] = adventure.intro_narrative
    narrative = generate_narrative(ai_context)
    engine.log_ai_narrative(narrative)

    return {
        "session_id": session.id,
        "name": session.name,
        "scene": engine.get_current_scene_context(),
        "narrative": narrative,
    }


@app.get("/api/sessions/{session_id}")
async def get_session_state(session_id: int):
    """Get current session state."""
    engine = GameEngine(session_id)
    if not engine.session:
        raise HTTPException(status_code=404, detail="Session not found")

    character = engine.get_character()

    return {
        "session_id": session_id,
        "name": engine.session.name,
        "state": engine.session.state,
        "scene": engine.get_current_scene_context(),
        "character": character.to_game_state() if character else None,
        "in_combat": engine.session.in_combat,
        "flags": engine.get_flags(),
    }


@app.get("/api/sessions/{session_id}/log")
async def get_session_log(session_id: int, limit: int = 50):
    """Get the narrative log for a session."""
    db = get_session(DB_PATH)
    try:
        entries = (
            db.query(NarrativeLog)
            .filter_by(session_id=session_id)
            .order_by(NarrativeLog.id.desc())
            .limit(limit)
            .all()
        )
        entries.reverse()
        return [
            {
                "id": e.id,
                "source": e.source,
                "type": e.entry_type,
                "content": e.content,
                "metadata": json.loads(e.metadata_json),
                "timestamp": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]
    finally:
        db.close()


# =========================================================================
# Game Action API
# =========================================================================

class ActionRequest(BaseModel):
    action_type: str
    params: dict = {}


@app.post("/api/sessions/{session_id}/action")
async def perform_action(session_id: int, req: ActionRequest):
    """Process a player action and return narrative + results."""
    engine = GameEngine(session_id)
    if not engine.session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Process the mechanical action
    result = engine.process_action(req.action_type, req.params)

    # Build AI context with the action result
    ai_context = engine.build_ai_context(result)

    # Generate narrative
    narrative = generate_narrative(ai_context)
    engine.log_ai_narrative(narrative)

    # Get updated state
    character = engine.get_character()
    scene = engine.get_current_scene_context()

    return {
        "narrative": narrative,
        "action_result": {
            "type": result.action_type.value,
            "success": result.success,
            "rolls": result.roll_results,
            "items_found": result.items_found,
            "damage_dealt": result.damage_dealt,
            "damage_taken": result.damage_taken,
            "scene_changed": result.scene_changed,
            "combat_started": result.combat_started,
            "combat_ended": result.combat_ended,
            "error": result.error,
        },
        "scene": scene,
        "character": character.to_game_state() if character else None,
        "in_combat": engine.session.in_combat,
    }


class StartCombatRequest(BaseModel):
    encounter_id: str


@app.post("/api/sessions/{session_id}/combat/start")
async def start_combat(session_id: int, req: StartCombatRequest):
    """Start a combat encounter."""
    engine = GameEngine(session_id)
    if not engine.session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = engine.start_combat(req.encounter_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Generate combat start narrative
    ai_context = engine.build_ai_context()
    ai_context["last_action"] = {
        "type": "combat_start",
        "success": True,
        "narrative_context": f"Combat begins! {result['description']}",
        "combat_started": True,
        "rolls": [],
    }
    narrative = generate_narrative(ai_context)
    engine.log_ai_narrative(narrative, entry_type="combat")

    return {
        "narrative": narrative,
        "combat": result,
    }


class EndCombatRequest(BaseModel):
    encounter_id: str


@app.post("/api/sessions/{session_id}/combat/end")
async def end_combat(session_id: int, req: EndCombatRequest):
    """End a combat encounter."""
    engine = GameEngine(session_id)
    result = engine.end_combat(req.encounter_id)
    return result


@app.get("/api/sessions/{session_id}/combat/entities")
async def get_combat_entities(session_id: int):
    """Get current combat entities (monsters) for display."""
    engine = GameEngine(session_id)
    if not engine.session:
        raise HTTPException(status_code=404, detail="Session not found")
    entities = engine.get_combat_entities()
    return [
        {
            "name": e.name,
            "hp": f"{e.current_hp}/{e.max_hp}",
            "ac": e.armor_class,
            "alive": e.is_alive,
        }
        for e in entities
    ]


# =========================================================================
# Run
# =========================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
