"""
SRD Data Loader
Loads 5e SRD JSON data into SQLite for the game engine.
We store the raw JSON blobs indexed by type and key for flexible lookup,
rather than trying to normalize everything into relational tables.
"""

import json
import sqlite3
from pathlib import Path

SRD_DATA_DIR = Path(__file__).parent.parent.parent / "5e-database" / "src" / "2014"

# Map of data type -> filename
SRD_FILES = {
    "ability_scores": "5e-SRD-Ability-Scores.json",
    "alignments": "5e-SRD-Alignments.json",
    "backgrounds": "5e-SRD-Backgrounds.json",
    "classes": "5e-SRD-Classes.json",
    "conditions": "5e-SRD-Conditions.json",
    "damage_types": "5e-SRD-Damage-Types.json",
    "equipment_categories": "5e-SRD-Equipment-Categories.json",
    "equipment": "5e-SRD-Equipment.json",
    "feats": "5e-SRD-Feats.json",
    "features": "5e-SRD-Features.json",
    "languages": "5e-SRD-Languages.json",
    "levels": "5e-SRD-Levels.json",
    "magic_items": "5e-SRD-Magic-Items.json",
    "magic_schools": "5e-SRD-Magic-Schools.json",
    "monsters": "5e-SRD-Monsters.json",
    "proficiencies": "5e-SRD-Proficiencies.json",
    "races": "5e-SRD-Races.json",
    "skills": "5e-SRD-Skills.json",
    "spells": "5e-SRD-Spells.json",
    "subclasses": "5e-SRD-Subclasses.json",
    "subraces": "5e-SRD-Subraces.json",
    "traits": "5e-SRD-Traits.json",
    "weapon_properties": "5e-SRD-Weapon-Properties.json",
}


def init_srd_db(db_path: str = "game.db") -> None:
    """Initialize the SRD reference data table and load all JSON data."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # SRD reference data - stores the raw JSON for each entry
    cur.execute("""
        CREATE TABLE IF NOT EXISTS srd_data (
            data_type TEXT NOT NULL,
            index_key TEXT NOT NULL,
            name TEXT NOT NULL,
            data JSON NOT NULL,
            PRIMARY KEY (data_type, index_key)
        )
    """)

    # Index for fast lookups by type
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_srd_type ON srd_data(data_type)
    """)

    # Check if data already loaded
    cur.execute("SELECT COUNT(*) FROM srd_data")
    count = cur.fetchone()[0]
    if count > 0:
        print(f"SRD data already loaded ({count} entries). Skipping.")
        conn.close()
        return

    # Load each JSON file
    total = 0
    for data_type, filename in SRD_FILES.items():
        filepath = SRD_DATA_DIR / filename
        if not filepath.exists():
            print(f"  WARNING: {filename} not found, skipping")
            continue

        with open(filepath) as f:
            entries = json.load(f)

        for entry in entries:
            index_key = entry.get("index", "")
            name = entry.get("name", "")
            cur.execute(
                "INSERT OR REPLACE INTO srd_data (data_type, index_key, name, data) VALUES (?, ?, ?, ?)",
                (data_type, index_key, name, json.dumps(entry)),
            )
        total += len(entries)
        print(f"  Loaded {len(entries):>4} {data_type}")

    conn.commit()
    conn.close()
    print(f"\nTotal SRD entries loaded: {total}")


def get_srd_entry(db_path: str, data_type: str, index_key: str) -> dict | None:
    """Fetch a single SRD entry by type and index key."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT data FROM srd_data WHERE data_type = ? AND index_key = ?",
        (data_type, index_key),
    )
    row = cur.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def get_srd_list(db_path: str, data_type: str) -> list[dict]:
    """Fetch all SRD entries of a given type."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT index_key, name FROM srd_data WHERE data_type = ? ORDER BY name",
        (data_type,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"index": row[0], "name": row[1]} for row in rows]


def search_srd(db_path: str, data_type: str, search: str) -> list[dict]:
    """Search SRD entries by name (case-insensitive partial match)."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT index_key, name FROM srd_data WHERE data_type = ? AND name LIKE ? ORDER BY name",
        (data_type, f"%{search}%"),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"index": row[0], "name": row[1]} for row in rows]


if __name__ == "__main__":
    print("Loading 5e SRD data into game.db...")
    init_srd_db()
    print("\nDone! Testing lookups...")

    # Quick tests
    goblin = get_srd_entry("game.db", "monsters", "goblin")
    print(f"\nGoblin HP: {goblin['hit_points']}, AC: {goblin['armor_class'][0]['value']}")

    races = get_srd_list("game.db", "races")
    print(f"Races: {[r['name'] for r in races]}")

    fire_spells = search_srd("game.db", "spells", "Fire")
    print(f"Fire spells: {[s['name'] for s in fire_spells]}")
