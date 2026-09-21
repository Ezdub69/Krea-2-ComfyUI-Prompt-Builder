"""SQLite library: presets grouped into collections, plus the queries the UI needs.

The library is built from build/out (the importer's staging files) and can be
re-imported at any time: user toggles (enabled flags) and user-added entries
survive a re-import.
"""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "library.db"
STAGING_DIR = ROOT / "build" / "out"

SECTION_ORDER = ["subject", "clothing", "action", "environment", "camera", "lighting", "style"]
SECTION_LABELS = {"subject": "Subject", "clothing": "Clothing", "action": "Action / Pose", "environment": "Environment",
                  "camera": "Camera", "lighting": "Lighting", "style": "Style"}
TIERS = ["basic", "detailed", "scene"]
TIER_LABELS = {"basic": "Basic", "detailed": "Detailed", "scene": "Scene"}
TIER_HELP = {
    "basic": "Short, everyday phrases",
    "detailed": "Richer, more specific descriptions",
    "scene": "Entries that already include other sections (for example environment or lighting)",
}
FACET_LABELS = {"type": "Hair type", "bottom": "Bottom", "venue": "Venue", "vibe": "Vibe", "place": "Place",
                "terrain": "Terrain", "tone": "Tone", "area": "Area", "garment": "Garment", "posture": "Posture",
                "colour": "Colour"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    display_name TEXT NOT NULL,
    section TEXT NOT NULL,
    slot TEXT NOT NULL,
    tier TEXT NOT NULL,
    grp TEXT NOT NULL,
    group_rank INTEGER NOT NULL DEFAULT 999,
    format TEXT,
    content_level TEXT NOT NULL DEFAULT 'general',
    weight REAL NOT NULL DEFAULT 1.0,
    requires_reference INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    entry_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS collection_themes (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    theme TEXT NOT NULL,
    PRIMARY KEY (collection_id, theme)
);
CREATE TABLE IF NOT EXISTS collection_covers (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    PRIMARY KEY (collection_id, section)
);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    origin TEXT NOT NULL DEFAULT 'imported',
    source_line INTEGER,
    label TEXT,
    text TEXT NOT NULL,
    vibe TEXT,
    form TEXT,
    flags TEXT,
    mentions TEXT,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_entries_collection ON entries(collection_id);
CREATE TABLE IF NOT EXISTS entry_facets (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    facet TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (entry_id, facet)
);
CREATE INDEX IF NOT EXISTS idx_entry_facets ON entry_facets(facet, value);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS saved_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    picks TEXT NOT NULL,
    adult INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
"""

TIER_RANK_SQL = "CASE c.tier WHEN 'basic' THEN 0 WHEN 'detailed' THEN 1 ELSE 2 END"


def get_connection(path=None):
    path = Path(path) if path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))
    conn.commit()


def library_is_empty(conn):
    return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def import_library(conn, staging_dir=None):
    d = Path(staging_dir) if staging_dir is not None else STAGING_DIR
    collections = json.loads((d / "collections.json").read_text(encoding="utf-8"))
    entries = [json.loads(line) for line in (d / "staging_entries.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    with conn:
        for c in collections:
            conn.execute(
                """INSERT INTO collections (id, source_file, display_name, section, slot, tier, grp, group_rank, format,
                       content_level, weight, requires_reference, enabled, entry_count, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET source_file=excluded.source_file, display_name=excluded.display_name,
                       section=excluded.section, slot=excluded.slot, tier=excluded.tier, grp=excluded.grp,
                       group_rank=excluded.group_rank, format=excluded.format, content_level=excluded.content_level,
                       weight=excluded.weight, requires_reference=excluded.requires_reference,
                       entry_count=excluded.entry_count, notes=excluded.notes""",
                (c["id"], c["source_file"], c["display_name"], c["section"], c["slot"], c["tier"], c["group"],
                 c.get("group_rank", 999), c.get("format"), c["content_level"], c["weight"],
                 int(c["requires_reference"]), int(c["enabled"]), c["entry_count"], c.get("notes") or None))
            conn.execute("DELETE FROM collection_themes WHERE collection_id = ?", (c["id"],))
            conn.executemany("INSERT INTO collection_themes (collection_id, theme) VALUES (?, ?)",
                             [(c["id"], t) for t in c["theme"]])
            conn.execute("DELETE FROM collection_covers WHERE collection_id = ?", (c["id"],))
            conn.executemany("INSERT INTO collection_covers (collection_id, section) VALUES (?, ?)",
                             [(c["id"], s) for s in c["covers"]])

        new_ids = {e["id"] for e in entries}
        old_ids = {r["id"] for r in conn.execute("SELECT id FROM entries WHERE origin = 'imported'")}
        gone = sorted(old_ids - new_ids)
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            conn.execute(f"DELETE FROM entries WHERE id IN ({','.join('?' * len(chunk))})", chunk)

        conn.execute("DELETE FROM entry_facets WHERE entry_id IN (SELECT id FROM entries WHERE origin = 'imported')")
        for e in entries:
            conn.execute(
                """INSERT INTO entries (id, collection_id, origin, source_line, label, text, vibe, form, flags, mentions)
                   VALUES (?, ?, 'imported', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET collection_id=excluded.collection_id, source_line=excluded.source_line,
                       label=excluded.label, text=excluded.text, vibe=excluded.vibe, form=excluded.form,
                       flags=excluded.flags, mentions=excluded.mentions""",
                (e["id"], e["collection"], e["source_line"], e.get("label"), e["text"], e.get("vibe"), e.get("form"),
                 json.dumps(e["flags"]) if e.get("flags") else None,
                 json.dumps(e["mentions"]) if e.get("mentions") else None))
        conn.executemany("INSERT INTO entry_facets (entry_id, facet, value) VALUES (?, ?, ?)",
                         [(e["id"], k, v) for e in entries for k, v in e.get("facets", {}).items()])

        stale = [r["id"] for r in conn.execute(
            "SELECT c.id FROM collections c WHERE NOT EXISTS (SELECT 1 FROM entries e WHERE e.collection_id = c.id)")]
        conn.executemany("DELETE FROM collections WHERE id = ?", [(i,) for i in stale])
    set_meta(conn, "library_signature", staging_signature(d))
    return {"collections": len(collections), "entries": len(entries), "removed_entries": len(gone)}


# ---- keeping the library in step with the shipped preset data ------------------------------------------------------------
def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    conn.commit()


def staging_signature(staging_dir=None):
    """A fingerprint of the shipped preset data: it changes whenever the presets that come with the app change."""
    d = Path(staging_dir) if staging_dir is not None else STAGING_DIR
    digest = hashlib.sha256()
    for name in ("collections.json", "staging_entries.jsonl"):
        digest.update((d / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ensure_library(conn, force=False, staging_dir=None):
    """Make sure the library matches the preset data that ships with the app.

    Returns 'imported' (first start, a newer version of the presets, or force=True), 'current' (nothing to do) or
    'missing' (no library and no preset data to build one from). A refresh keeps everything of yours: your own lists and
    entries, on/off choices and saved prompts."""
    d = Path(staging_dir) if staging_dir is not None else STAGING_DIR
    if not (d / "collections.json").exists() or not (d / "staging_entries.jsonl").exists():
        return "missing" if library_is_empty(conn) else "current"
    if force or library_is_empty(conn) or get_meta(conn, "library_signature") != staging_signature(d):
        import_library(conn, d)
        return "imported"
    return "current"


def sections_tree(conn, tiers, show_adult, include_disabled=False):
    """[(section, [(group, [collection row + n])])] in display order; only lists that match the filters."""
    if not tiers:
        return []
    sql = f"""SELECT c.*, (SELECT COUNT(*) FROM entries e WHERE e.collection_id = c.id AND e.enabled = 1) AS n
              FROM collections c WHERE {'1 = 1' if include_disabled else 'c.enabled = 1'}
              AND c.tier IN ({','.join('?' * len(tiers))})"""
    params = list(tiers)
    if not show_adult:
        sql += " AND c.content_level != 'explicit'"
    sql += f" ORDER BY c.group_rank, {TIER_RANK_SQL}, c.display_name"
    by_section = {}
    for row in conn.execute(sql, params):
        by_section.setdefault(row["section"], {}).setdefault(row["grp"], []).append(row)
    return [(s, list(by_section[s].items())) for s in SECTION_ORDER if s in by_section]


def collection_facet_names(conn, collection_id):
    names = [r["facet"] for r in conn.execute(
        """SELECT DISTINCT ef.facet FROM entry_facets ef JOIN entries e ON e.id = ef.entry_id
           WHERE e.collection_id = ?""", (collection_id,))]
    return sorted(names, key=lambda n: (n != "colour", n))


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _entry_filter(ids, facets, query, include_disabled):
    sql = f"e.collection_id IN ({','.join('?' * len(ids))})"
    params = list(ids)
    if not include_disabled:
        sql += " AND e.enabled = 1"
    for facet, value in (facets or {}).items():
        sql += " AND EXISTS (SELECT 1 FROM entry_facets ef WHERE ef.entry_id = e.id AND ef.facet = ? AND ef.value = ?)"
        params += [facet, value]
    for word in (query or "").split():
        sql += " AND (e.text LIKE ? ESCAPE '\\' OR COALESCE(e.label, '') LIKE ? ESCAPE '\\')"
        params += [_like(word), _like(word)]
    return sql, params


def facet_counts(conn, ids, facet_names, active, query="", include_disabled=False):
    out = {}
    for name in facet_names:
        others = {k: v for k, v in active.items() if k != name}
        where, params = _entry_filter(ids, others, query, include_disabled)
        rows = conn.execute(
            f"""SELECT ef.value AS value, COUNT(*) AS n FROM entries e
                JOIN entry_facets ef ON ef.entry_id = e.id AND ef.facet = ?
                WHERE {where} GROUP BY ef.value""", [name] + params)
        out[name] = [(r["value"], r["n"]) for r in rows]
    return out


def count_entries(conn, ids, facets=None, query="", include_disabled=False):
    if not ids:
        return 0
    where, params = _entry_filter(ids, facets, query, include_disabled)
    return conn.execute(f"SELECT COUNT(*) FROM entries e WHERE {where}", params).fetchone()[0]


def search_entries(conn, ids, facets=None, query="", include_disabled=False, limit=500):
    if not ids:
        return []
    where, params = _entry_filter(ids, facets, query, include_disabled)
    return conn.execute(
        f"""SELECT e.id, e.label, e.text, e.vibe, e.enabled, e.source_line, e.origin, c.id AS collection_id,
                   c.display_name, c.section, c.grp, c.tier
            FROM entries e JOIN collections c ON c.id = e.collection_id
            WHERE {where} ORDER BY c.group_rank, {TIER_RANK_SQL}, c.display_name, e.source_line LIMIT ?""",
        params + [limit]).fetchall()


def get_entry(conn, entry_id):
    row = conn.execute(
        """SELECT e.*, c.display_name, c.section, c.slot, c.grp, c.tier, c.requires_reference, c.content_level
           FROM entries e JOIN collections c ON c.id = e.collection_id WHERE e.id = ?""", (entry_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["flags"] = json.loads(row["flags"]) if row["flags"] else []
    out["facets"] = {r["facet"]: r["value"] for r in conn.execute(
        "SELECT facet, value FROM entry_facets WHERE entry_id = ? ORDER BY facet", (entry_id,))}
    out["covers"] = [r["section"] for r in conn.execute(
        "SELECT section FROM collection_covers WHERE collection_id = ? ORDER BY section", (row["collection_id"],))]
    return out


def wildcard_collections(conn, section=None, slots=None, tiers=None, show_adult=False, standalone=False):
    """Lists the wildcard may draw from: enabled, not reference-only, with at least one enabled entry.

    standalone=True keeps only lists that describe their own section and nothing else (no whole-scene lists)."""
    sql = """SELECT c.* FROM collections c WHERE c.enabled = 1 AND c.requires_reference = 0
             AND EXISTS (SELECT 1 FROM entries e WHERE e.collection_id = c.id AND e.enabled = 1)"""
    params = []
    if section:
        sql += " AND c.section = ?"
        params.append(section)
    if slots:
        sql += f" AND c.slot IN ({','.join('?' * len(slots))})"
        params += list(slots)
    if tiers:
        sql += f" AND c.tier IN ({','.join('?' * len(tiers))})"
        params += list(tiers)
    if not show_adult:
        sql += " AND c.content_level != 'explicit'"
    if standalone:
        sql += " AND c.tier != 'scene' AND NOT EXISTS (SELECT 1 FROM collection_covers cv WHERE cv.collection_id = c.id)"
    return conn.execute(sql + " ORDER BY c.id", params).fetchall()


def enabled_entry_texts(conn, collection_id):
    """[(entry id, text)] for the enabled entries of one list."""
    return [(r["id"], r["text"]) for r in conn.execute(
        "SELECT id, text FROM entries WHERE collection_id = ? AND enabled = 1 ORDER BY source_line, id", (collection_id,))]


def enabled_entry_rows(conn, collection_id):
    """id, text and mentions of the enabled entries of one list."""
    return conn.execute("SELECT id, text, mentions FROM entries WHERE collection_id = ? AND enabled = 1 ORDER BY source_line, id",
                        (collection_id,)).fetchall()


def enabled_entry_ids(conn, collection_id):
    return [r["id"] for r in conn.execute(
        "SELECT id FROM entries WHERE collection_id = ? AND enabled = 1 ORDER BY source_line, id", (collection_id,))]


# ---- your own presets -------------------------------------------------------------------------------------------------
USER_GROUP = "My presets"
USER_PREFIX = "user/"
SECTION_SLOTS = {
    "subject": ["age", "skin tone", "hair colour", "hair style", "eye colour", "body", "bust size", "bust shape",
                "basic expression", "expression and eyes", "makeup", "skin", "tattoos", "piercings"],
    "clothing": ["outfit"],
    "action": ["pose", "adult scenes"],
    "environment": ["setting", "general setting", "colour palette"],
    "camera": ["angle", "framing", "lens and film look"],
    "lighting": ["basic lighting", "dramatic lighting"],
    "style": ["colour grading", "photo style", "movie theme"],
}
SLOT_LABELS = {
    "pose": "Pose", "adult scenes": "Adult scenes", "outfit": "Outfit", "setting": "Setting (detailed places)",
    "general setting": "Setting (simple places)", "colour palette": "Colour palette", "angle": "Camera angle",
    "framing": "Framing", "lens and film look": "Lens and film look", "basic lighting": "Lighting (simple)",
    "dramatic lighting": "Lighting (dramatic)", "colour grading": "Colour grading", "photo style": "Photo style",
    "movie theme": "Movie theme", "basic expression": "Expression (simple)", "expression and eyes": "Expression and eyes",
    "skin": "Skin detail",
}


def slot_label(slot):
    return SLOT_LABELS.get(slot, slot.capitalize())


def is_user_collection(collection_id):
    return str(collection_id).startswith(USER_PREFIX)


def normalise_entry_text(text):
    """One preset line: bullets and numbering removed, spaces collapsed."""
    text = " ".join((text or "").split())
    while text[:1] in ("-", "*", "•", "–", "—") and text[1:2] in (" ", ""):
        text = text[1:].lstrip()
    head, dot, rest = text.partition(". ")
    if dot and head.isdigit():
        text = rest
    return text.strip()


def _entry_key(text):
    return normalise_entry_text(text).lower().rstrip(".")


def add_user_entries(conn, collection_id, texts):
    """Add lines to a list. Returns (added entry ids, skipped lines that were already in the list)."""
    from app.composer import guess_form
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise KeyError(collection_id)
    seen = {_entry_key(r["text"]) for r in conn.execute("SELECT text FROM entries WHERE collection_id = ?", (collection_id,))}
    line = conn.execute("SELECT COALESCE(MAX(source_line), 0) FROM entries WHERE collection_id = ?", (collection_id,)).fetchone()[0]
    added, skipped = [], []
    with conn:
        for raw in texts:
            text = normalise_entry_text(raw)
            if not text:
                continue
            key = _entry_key(text)
            if key in seen:
                skipped.append(text)
                continue
            seen.add(key)
            line += 1
            entry_id = "user-" + uuid.uuid4().hex
            conn.execute(
                "INSERT INTO entries (id, collection_id, origin, source_line, label, text, form) VALUES (?, ?, 'user', ?, NULL, ?, ?)",
                (entry_id, collection_id, line, text, guess_form(text)))
            added.append(entry_id)
        _refresh_entry_count(conn, collection_id)
    return added, skipped


def update_user_entry(conn, entry_id, text):
    """Change the text of an entry you added. Returns 'ok', 'empty', 'duplicate' or 'not_yours'."""
    from app.composer import guess_form
    row = conn.execute("SELECT collection_id, origin FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None or row["origin"] != "user":
        return "not_yours"
    text = normalise_entry_text(text)
    if not text:
        return "empty"
    others = {_entry_key(r["text"]) for r in conn.execute(
        "SELECT text FROM entries WHERE collection_id = ? AND id != ?", (row["collection_id"], entry_id))}
    if _entry_key(text) in others:
        return "duplicate"
    with conn:
        conn.execute("UPDATE entries SET text = ?, form = ? WHERE id = ?", (text, guess_form(text), entry_id))
    return "ok"


def delete_user_entry(conn, entry_id):
    row = conn.execute("SELECT collection_id, origin FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None or row["origin"] != "user":
        return False
    with conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        _refresh_entry_count(conn, row["collection_id"])
    return True


def _refresh_entry_count(conn, collection_id):
    conn.execute("UPDATE collections SET entry_count = (SELECT COUNT(*) FROM entries WHERE collection_id = ?) WHERE id = ?",
                 (collection_id, collection_id))


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "list"


def create_user_collection(conn, name, section, slot, tier, texts, grp=None, content_level="general", covers=()):
    """Create your own list with its first entries. Returns the new list's id."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("A list needs a name")
    if section not in SECTION_SLOTS or slot not in SECTION_SLOTS[section]:
        raise ValueError(f"'{slot}' is not a list type of {section}")
    if tier not in TIERS:
        raise ValueError(f"Unknown tier {tier}")
    if content_level == "explicit" and section != "action":
        raise ValueError("Only action lists can be marked as adult")
    if not any(normalise_entry_text(t) for t in texts):
        raise ValueError("A list needs at least one entry")
    grp = " ".join((grp or USER_GROUP).split()) or USER_GROUP
    base = USER_PREFIX + _slug(name)
    collection_id, n = base, 1
    while conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone():
        n += 1
        collection_id = f"{base}-{n}"
    rank = conn.execute("SELECT group_rank FROM collections WHERE section = ? AND grp = ? LIMIT 1", (section, grp)).fetchone()
    with conn:
        conn.execute(
            """INSERT INTO collections (id, source_file, display_name, section, slot, tier, grp, group_rank, format,
                   content_level, weight, requires_reference, enabled, entry_count, notes)
               VALUES (?, '(added in the app)', ?, ?, ?, ?, ?, ?, 'plain', ?, 1.0, 0, 1, 0, 'Added by you')""",
            (collection_id, name, section, slot, tier, grp, rank["group_rank"] if rank else 900, content_level))
        if tier == "scene":
            conn.executemany("INSERT OR IGNORE INTO collection_covers (collection_id, section) VALUES (?, ?)",
                             [(collection_id, s) for s in covers if s in SECTION_SLOTS and s != section])
    add_user_entries(conn, collection_id, texts)
    return collection_id


def delete_user_collection(conn, collection_id):
    if not is_user_collection(collection_id):
        return False
    with conn:
        conn.execute("DELETE FROM entries WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    return True


def set_collection_enabled(conn, collection_id, enabled):
    conn.execute("UPDATE collections SET enabled = ? WHERE id = ?", (int(enabled), collection_id))
    conn.commit()


def groups_for_section(conn, section):
    """Existing group names of a section (your own group last)."""
    names = [r["grp"] for r in conn.execute(
        "SELECT grp FROM collections WHERE section = ? GROUP BY grp ORDER BY MIN(group_rank), grp", (section,))]
    return [g for g in names if g != USER_GROUP] + [USER_GROUP]


# ---- saved prompts --------------------------------------------------------------------------------------------------------
# Each saved prompt keeps the finished text and a snapshot of every pick, so it can be loaded back into the Builder even
# if the library has changed since (an entry you deleted, a library reset...).
ENTRY_SNAPSHOT_FIELDS = ("id", "section", "slot", "text", "form", "display_name", "tier", "grp", "covers", "mentions",
                         "label", "origin", "content_level")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _pack_picks(rows, locks=(), none_rows=()):
    """rows: {row key: entry dict}. Returns (json text, adult flag)."""
    kept = {key: {f: entry.get(f) for f in ENTRY_SNAPSHOT_FIELDS} for key, entry in rows.items() if entry}
    adult = any(e.get("content_level") == "explicit" or e.get("slot") == "adult scenes" for e in kept.values())
    return json.dumps({"rows": kept, "locks": sorted(locks), "none": sorted(none_rows)}), int(adult)


def save_prompt(conn, name, prompt_text, rows, locks=(), none_rows=(), notes=""):
    """Store a finished prompt with its picks. Returns the new saved prompt's id."""
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("A saved prompt needs a name")
    if not (prompt_text or "").strip():
        raise ValueError("There is no prompt to save")
    picks, adult = _pack_picks(rows, locks, none_rows)
    now = _now()
    with conn:
        cur = conn.execute(
            "INSERT INTO saved_prompts (name, created_at, updated_at, prompt_text, picks, adult, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, now, now, prompt_text, picks, adult, notes or ""))
    return cur.lastrowid


def update_saved_prompt(conn, saved_id, prompt_text, rows, locks=(), none_rows=()):
    """Replace the prompt and picks of an existing saved prompt (its name, notes and date of creation stay)."""
    if not (prompt_text or "").strip():
        raise ValueError("There is no prompt to save")
    picks, adult = _pack_picks(rows, locks, none_rows)
    with conn:
        cur = conn.execute("UPDATE saved_prompts SET prompt_text = ?, picks = ?, adult = ?, updated_at = ? WHERE id = ?",
                           (prompt_text, picks, adult, _now(), saved_id))
    return cur.rowcount == 1


def get_saved_prompt(conn, saved_id):
    row = conn.execute("SELECT * FROM saved_prompts WHERE id = ?", (saved_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    data = json.loads(row["picks"])
    out["rows"], out["locks"], out["none"] = data.get("rows", {}), data.get("locks", []), data.get("none", [])
    return out


def list_saved_prompts(conn, query="", include_adult=False):
    """(prompts newest first, number hidden because they contain adult scenes)."""
    sql, params = "SELECT id, name, created_at, updated_at, prompt_text, adult, notes FROM saved_prompts WHERE 1 = 1", []
    for word in (query or "").split():
        sql += " AND (name LIKE ? ESCAPE '\\' OR prompt_text LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')"
        params += [_like(word)] * 3
    rows = conn.execute(sql + " ORDER BY updated_at DESC, id DESC", params).fetchall()
    shown = [r for r in rows if include_adult or not r["adult"]]
    return shown, len(rows) - len(shown)


def rename_saved_prompt(conn, saved_id, name):
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("A saved prompt needs a name")
    with conn:
        conn.execute("UPDATE saved_prompts SET name = ? WHERE id = ?", (name, saved_id))


def set_saved_notes(conn, saved_id, notes):
    with conn:
        conn.execute("UPDATE saved_prompts SET notes = ? WHERE id = ?", (notes or "", saved_id))


def delete_saved_prompt(conn, saved_id):
    with conn:
        return conn.execute("DELETE FROM saved_prompts WHERE id = ?", (saved_id,)).rowcount == 1


# ---- reset to default ---------------------------------------------------------------------------------------------------
BACKUP_KEEP = 10


def _db_file(conn):
    for row in conn.execute("PRAGMA database_list"):
        if row["name"] == "main":
            return Path(row["file"]) if row["file"] else None
    return None


def backup_folder(conn):
    file = _db_file(conn)
    return file.parent / "backups" if file else None


def backup_library(conn, keep=BACKUP_KEEP):
    """Copy the whole library database to data/backups/library-<date>-<time>.db. Returns the new file (None if in memory)."""
    folder = backup_folder(conn)
    if folder is None:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target, n = folder / f"library-{stamp}.db", 1
    while target.exists():
        n += 1
        target = folder / f"library-{stamp}-{n}.db"
    conn.commit()
    copy = sqlite3.connect(str(target))
    try:
        conn.backup(copy)
    finally:
        copy.close()
    for old in sorted(folder.glob("library-*.db"), key=lambda f: f.stat().st_mtime, reverse=True)[keep:]:
        old.unlink()
    return target


def reset_preview(conn):
    """What a reset would remove, for the confirmation message."""
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "user_lists": one("SELECT COUNT(*) FROM collections WHERE id LIKE 'user/%'"),
        "user_entries": one("SELECT COUNT(*) FROM entries WHERE origin = 'user'"),
        "switched_off_lists": one("SELECT COUNT(*) FROM collections WHERE enabled = 0"),
        "switched_off_entries": one("SELECT COUNT(*) FROM entries WHERE enabled = 0"),
        "settings": one("SELECT COUNT(*) FROM settings"),
    }


def reset_library(conn, staging_dir=None, keep_backups=BACKUP_KEEP):
    """Put the library back exactly as it was on a first install.

    The original data (build/out) is checked first and a backup copy of the current library is made; only then is
    everything replaced - your lists and entries, on/off switches and saved options - in a single transaction, so a
    failure leaves the library as it was. Raises FileNotFoundError (nothing touched) if the original data is missing."""
    d = Path(staging_dir) if staging_dir is not None else STAGING_DIR
    for name in ("collections.json", "staging_entries.jsonl"):
        if not (d / name).exists():
            raise FileNotFoundError(str(d / name))
    json.loads((d / "collections.json").read_text(encoding="utf-8"))   # unreadable original data must not wipe anything
    removed = reset_preview(conn)
    backup = backup_library(conn, keep_backups)
    try:
        for table in ("entry_facets", "entries", "collection_covers", "collection_themes", "collections", "settings"):
            conn.execute(f"DELETE FROM {table}")
        imported = import_library(conn, d)
    except Exception:
        conn.rollback()
        raise
    return dict(removed, backup=backup, collections=imported["collections"], entries=imported["entries"])


def picker_collections(conn, section, slots=None, show_adult=False):
    """Lists offered when picking an entry by hand for one section (or a few slots of it), with enabled-entry counts."""
    sql = """SELECT c.*, (SELECT COUNT(*) FROM entries e WHERE e.collection_id = c.id AND e.enabled = 1) AS n
             FROM collections c WHERE c.enabled = 1 AND c.section = ?"""
    params = [section]
    if slots:
        sql += f" AND c.slot IN ({','.join('?' * len(slots))})"
        params += list(slots)
    if not show_adult:
        sql += " AND c.content_level != 'explicit'"
    sql += f" ORDER BY c.group_rank, {TIER_RANK_SQL}, c.display_name"
    return [r for r in conn.execute(sql, params) if r["n"]]


def set_entry_enabled(conn, entry_id, enabled):
    conn.execute("UPDATE entries SET enabled = ? WHERE id = ?", (int(enabled), entry_id))
    conn.commit()
