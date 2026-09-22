"""Random prompt picks. A list is chosen first, then an entry inside it, so huge lists cannot dominate."""
import json
import random

from app import db, placematch
from app.composer import (HAIR_COLOUR_WORDS, entry_mentions_body_shape, entry_mentions_clothing, mentions_eye_colour,
                          mentions_piercings, mentions_tattoos)

# (row key, label, slots in the library, chance the wildcard fills it)
SUBJECT_ROWS = [
    ("age", "Age", ["age"], 1.0),
    ("skin tone", "Skin tone", ["skin tone"], 0.9),
    ("hair colour", "Hair colour", ["hair colour"], 0.9),
    ("hair style", "Hair style", ["hair style"], 0.8),
    ("eye colour", "Eye colour", ["eye colour"], 0.8),
    ("body", "Body", ["body"], 0.5),
    ("bust size", "Bust size", ["bust size"], 0.4),
    ("bust shape", "Bust shape", ["bust shape"], 0.3),
    ("expression", "Expression", ["basic expression", "expression and eyes"], 0.9),
    ("makeup", "Makeup", ["makeup"], 0.6),
    ("skin", "Skin detail", ["skin"], 0.3),
    ("tattoos", "Tattoos", ["tattoos"], 0.25),
    ("piercings", "Piercings", ["piercings"], 0.15),
]
SUBJECT_SLOTS = {slot: key for key, _label, slots, _chance in SUBJECT_ROWS for slot in slots}
# only used when whole-scene presets are switched on: chance that each section is filled at all
SECTION_CHANCE = {"action": 1.0, "clothing": 0.95, "environment": 1.0, "camera": 0.9, "lighting": 0.9, "style": 0.6}
PICK_ORDER = ["action", "environment", "clothing", "camera", "lighting", "style"]   # clothing follows pose + setting
ADULT_SLOT = "adult scenes"


def row_key(entry):
    """The builder row an entry belongs to: the section, or 'subject:<row>' for subject details."""
    if entry["section"] == "subject":
        return "subject:" + SUBJECT_SLOTS.get(entry["slot"], entry["slot"])
    return entry["section"]


_avoid_eye_colour = [False]     # set while drawing when the user has chosen "None" for eye colour
_avoid_tattoos = [False]        # set while drawing when the user has chosen "None" for tattoos
_avoid_piercings = [False]      # set while drawing when the user has chosen "None" for piercings
_avoid_clothing = [False]       # set while drawing when a separate Clothing pick is (or will be) part of the prompt
_avoid_body_shape = [False]     # set while drawing when a Subject body/bust pick is locked in place


def _entry_id(conn, rng, collection_id, avoid_clothing=False, avoid_body_shape=False):
    """A random enabled entry of one list.

    With eye colour/tattoos/piercings switched off, never one that names an eye colour/tattoo/piercing. With
    avoid_clothing (a Clothing pick is in play), never one that names garments of its own - such a pose would put a
    second outfit into the prompt. With avoid_body_shape (a Subject body/bust pick is locked), never one that names
    its own bust size/shape or build."""
    if not (_avoid_eye_colour[0] or _avoid_tattoos[0] or _avoid_piercings[0] or avoid_clothing or avoid_body_shape):
        return rng.choice(db.enabled_entry_ids(conn, collection_id))
    fine = [row["id"] for row in db.enabled_entry_rows(conn, collection_id)
            if not (_avoid_eye_colour[0] and mentions_eye_colour(row["text"]))
            and not (_avoid_tattoos[0] and mentions_tattoos(row["text"]))
            and not (_avoid_piercings[0] and mentions_piercings(row["text"]))
            and not (avoid_clothing and entry_mentions_clothing(row))
            and not (avoid_body_shape and entry_mentions_body_shape(row))]
    return rng.choice(fine) if fine else None


def _pick_from(conn, rng, lists, weights=None):
    lists = list(lists)
    weights = list(weights or [c["weight"] for c in lists])
    while lists:
        index = rng.choices(range(len(lists)), weights=weights)[0]
        avoid_clothing = _avoid_clothing[0] and lists[index]["section"] != "clothing"   # clothing lists are the clothing
        avoid_body_shape = _avoid_body_shape[0] and lists[index]["section"] != "subject"   # subject lists are the body/bust
        entry_id = _entry_id(conn, rng, lists[index]["id"], avoid_clothing, avoid_body_shape)
        if entry_id is not None:
            return db.get_entry(conn, entry_id)
        del lists[index], weights[index]
    return None


def _draw(conn, rng, section=None, slots=None, tiers=None, show_adult=False, standalone=False):
    return _pick_from(conn, rng, db.wildcard_collections(conn, section, slots, tiers, show_adult, standalone))


def _draw_adult_action(conn, rng):
    lists = [c for c in db.wildcard_collections(conn, "action", None, None, True) if c["content_level"] == "explicit"]
    return _pick_from(conn, rng, lists)


def _draw_environment(conn, rng, allowed, tiers, show_adult, standalone):
    """An environment entry that suits the pose's kind of place; falls back to any if nothing fits."""
    lists = list(db.wildcard_collections(conn, "environment", None, tiers, show_adult, standalone))
    while lists:
        chosen = rng.choices(lists, weights=[c["weight"] * (0.25 if c["slot"] == "colour palette" else 1) for c in lists])[0]
        palette = chosen["slot"] == "colour palette"
        fits = [i for i, t in db.enabled_entry_texts(conn, chosen["id"])
                if placematch.environment_fits(t, palette, allowed) and not (_avoid_eye_colour[0] and mentions_eye_colour(t))
                and not (_avoid_tattoos[0] and mentions_tattoos(t)) and not (_avoid_piercings[0] and mentions_piercings(t))]
        if fits:
            return db.get_entry(conn, rng.choice(fits))
        lists.remove(chosen)
    return _draw(conn, rng, section="environment", tiers=tiers, show_adult=show_adult, standalone=standalone)


def _draw_clothing(conn, rng, action, environment, tiers, show_adult, standalone):
    """A clothing entry that suits the pose and the setting (no gym wear on a bed, no lingerie in a hotel lobby)."""
    lists = list(db.wildcard_collections(conn, "clothing", None, tiers, show_adult, standalone))
    boosts = placematch.clothing_weights(
        [c["display_name"] for c in lists],
        action["display_name"] if action else "", action["text"] if action else "",
        environment["text"] if environment and environment["slot"] != "colour palette" else "")
    fitting = [c for c in lists if c["display_name"] in boosts] or lists
    return _pick_from(conn, rng, fitting, [c["weight"] * boosts.get(c["display_name"], 1.0) for c in fitting])


def _draw_subject_row(conn, rng, key, subject, tiers, show_adult):
    slots = next(s for k, _l, s, _c in SUBJECT_ROWS if k == key)

    def draw():
        # a detail with no list at the chosen level (age, eye colour, body and bust only have a Basic list; hair style and
        # skin detail only a Detailed one) uses the other level, so ticking one level never makes a row disappear
        return (_draw(conn, rng, section="subject", slots=slots, tiers=tiers, show_adult=show_adult)
                or _draw(conn, rng, section="subject", slots=slots, show_adult=show_adult))

    entry = draw()
    # a hair style that names its own colour would fight the colour already picked
    for _ in range(20):
        if not (entry and key == "hair style" and any(e["slot"] == "hair colour" for e in subject)
                and HAIR_COLOUR_WORDS.search(entry["text"])):
            break
        entry = draw()
    return entry


def sections_described_by(entry):
    """Other sections an action already describes and that the wildcard should therefore leave out.

    Adult scenes are whole photographs: they never get a separate clothing line (the scene is nude or dressed as it says)
    and skip any section their text mentions. Ordinary entries only skip what their list says it covers."""
    skip = set(entry["covers"])
    if entry["section"] != "clothing" and entry_mentions_clothing(entry):
        skip.add("clothing")   # a pose, scene or poster that names what she is wearing: no second outfit next to it
    if entry["slot"] == ADULT_SLOT:
        mentions = json.loads(entry["mentions"]) if entry.get("mentions") else {}
        skip |= {"clothing"} | (set(mentions) & {"environment", "camera", "lighting"})
    return skip


def wildcard_picks(conn, rng=None, tiers=("basic", "detailed"), show_adult=False, scenes=False, scene_chance=0.25,
                   locked=None, detail=1.0, adult_chance=0.3, skip_rows=()):
    """{section: [entry]}.

    Default: every section is filled from lists that describe only that section, so the prompt always has the same
    seven paragraphs. With scenes=True, whole-scene presets may be drawn (a pose that already names its setting,
    a movie poster...); the sections they cover are then skipped and the structure varies.

    locked: picks to keep exactly as they are (same shape as the result); everything else is drawn around them.
    detail: scales how many optional subject details (hair style, makeup, tattoos...) are added; age is always drawn.
    adult_chance: with show_adult on, the chance that the action comes from the adult scenes list.
    skip_rows: rows to leave out entirely (for example 'subject:eye colour' for a character LoRA that already fixes it);
    with that row skipped, no entry that names an eye colour is drawn either.
    """
    _avoid_eye_colour[0] = "subject:eye colour" in skip_rows
    _avoid_tattoos[0] = "subject:tattoos" in skip_rows
    _avoid_piercings[0] = "subject:piercings" in skip_rows
    try:
        return _wildcard_picks(conn, rng or random.Random(), tiers, show_adult, scenes, scene_chance, locked, detail,
                               adult_chance, set(skip_rows))
    finally:
        _avoid_eye_colour[0] = False
        _avoid_tattoos[0] = False
        _avoid_piercings[0] = False
        _avoid_clothing[0] = False
        _avoid_body_shape[0] = False


def _wildcard_picks(conn, rng, tiers, show_adult, scenes, scene_chance, locked, detail, adult_chance, skip_rows):

    standalone = not scenes
    picks = {s: list(v) for s, v in (locked or {}).items() if v}
    locked_subject_keys = {row_key(e).split(":", 1)[1] for e in picks.get("subject", [])}
    _avoid_body_shape[0] = bool({"body", "bust size", "bust shape"} & locked_subject_keys)
    skip = set()
    for section, entries in picks.items():
        if section != "subject":
            skip |= sections_described_by(entries[0])
    if scenes and scene_chance and "action" not in picks and rng.random() < scene_chance:
        scene = _draw(conn, rng, tiers=["scene"], show_adult=False)
        if scene and scene["section"] != "subject" and scene["section"] not in picks:
            picks[scene["section"]] = [scene]
            skip |= sections_described_by(scene) | {scene["section"]}
    if show_adult and "action" not in picks and rng.random() < adult_chance:
        entry = _draw_adult_action(conn, rng)
        if entry:
            picks["action"] = [entry]
            skip |= sections_described_by(entry)
    for section in PICK_ORDER:
        if section in picks or section in skip or (scenes and rng.random() > SECTION_CHANCE[section]):
            continue
        _avoid_clothing[0] = "clothing" in picks or "clothing" not in skip   # a Clothing pick exists or is still to come
        entry = None
        for use_tiers in (tiers, None):   # if the chosen tiers leave a section empty, widen to every tier
            action = picks.get("action", [None])[0]
            if section == "environment":
                allowed = placematch.allowed_places(action["display_name"], action["text"]) if action else None
                entry = _draw_environment(conn, rng, allowed, use_tiers, False, standalone)
            elif section == "clothing":
                entry = _draw_clothing(conn, rng, action, picks.get("environment", [None])[0], use_tiers, False, standalone)
            else:
                entry = _draw(conn, rng, section=section, tiers=use_tiers, show_adult=False, standalone=standalone)
            if entry or scenes:
                break
        if entry:
            picks[section] = [entry]
            skip |= sections_described_by(entry)
    _avoid_clothing[0] = "clothing" in picks or "clothing" not in skip
    action_entry = picks.get("action", [None])[0]
    action_claims_body_shape = action_entry is not None and entry_mentions_body_shape(action_entry)
    subject = list(picks.get("subject", []))
    have = {row_key(e).split(":", 1)[1] for e in subject}
    for key, _label, _slots, chance in SUBJECT_ROWS:
        if key in have or "subject:" + key in skip_rows:
            continue
        if action_claims_body_shape and key in ("body", "bust size", "bust shape"):
            continue   # the action already names its own bust size/shape or build; a second one would clash
        if key != "age" and rng.random() > min(1.0, chance * detail):
            continue
        entry = _draw_subject_row(conn, rng, key, subject, tiers, False)
        if entry:
            subject.append(entry)
    if subject:
        picks["subject"] = subject
    return picks


def reroll(conn, rng, row, picks, tiers=("basic", "detailed"), show_adult=False, adult_chance=0.3, skip_rows=()):
    """A fresh entry for one builder row ('action', 'clothing'..., or 'subject:<row>') given the rest of the picks."""
    _avoid_eye_colour[0] = "subject:eye colour" in skip_rows
    _avoid_tattoos[0] = "subject:tattoos" in skip_rows
    _avoid_piercings[0] = "subject:piercings" in skip_rows
    _avoid_clothing[0] = bool(picks.get("clothing")) and row != "clothing"   # a Clothing pick is in place: avoid a second outfit
    subject_keys = {row_key(e).split(":", 1)[1] for e in picks.get("subject", [])}
    body_rows = ("subject:body", "subject:bust size", "subject:bust shape")
    _avoid_body_shape[0] = bool({"body", "bust size", "bust shape"} & subject_keys) and row not in body_rows
    try:
        return _reroll(conn, rng, row, picks, tiers, show_adult, adult_chance)
    finally:
        _avoid_eye_colour[0] = False
        _avoid_tattoos[0] = False
        _avoid_piercings[0] = False
        _avoid_clothing[0] = False
        _avoid_body_shape[0] = False


def _reroll(conn, rng, row, picks, tiers, show_adult, adult_chance):
    action = picks.get("action", [None])[0]
    if row == "action":
        if show_adult and rng.random() < adult_chance:
            entry = _draw_adult_action(conn, rng)
            if entry:
                return entry
        return _draw(conn, rng, section="action", tiers=tiers, standalone=True) or _draw(conn, rng, section="action", standalone=True)
    if row == "environment":
        allowed = placematch.allowed_places(action["display_name"], action["text"]) if action else None
        return _draw_environment(conn, rng, allowed, tiers, False, True) or _draw_environment(conn, rng, allowed, None, False, True)
    if row == "clothing":
        return (_draw_clothing(conn, rng, action, picks.get("environment", [None])[0], tiers, False, True)
                or _draw_clothing(conn, rng, action, picks.get("environment", [None])[0], None, False, True))
    if row.startswith("subject:"):
        others = [e for e in picks.get("subject", []) if row_key(e) != row]
        return _draw_subject_row(conn, rng, row.split(":", 1)[1], others, tiers, False)
    return _draw(conn, rng, section=row, tiers=tiers, standalone=True) or _draw(conn, rng, section=row, standalone=True)
