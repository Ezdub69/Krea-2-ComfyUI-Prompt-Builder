"""Keeps the wildcard's Action and Environment picks in the same kind of place (no headboard pose on a coastal bridge).

Every environment / pose text is tagged with the kinds of place it describes; each Action list says which kinds fit it.
"""
import re
from functools import lru_cache

PLACE_WORDS = {
    "bedroom": r"bed\b|beds\b|bedroom|bedding|headboard|pillows?|duvet|bedsheet|four-poster|canopy bed",
    "bathroom": r"bath|shower|vanity|steam|sink",
    "hotel": r"hotel|suite|resort|penthouse|motel",
    "home": r"living room|sofa|couch|apartment|home\b|house|cottage|cabin|loft|fireplace|armchair|"
            r"hallway|bookshelf|nursery|wardrobe|closet|dressing room|residential",
    "kitchen": r"kitchen|dining|pantry|breakfast bar",
    "studio": r"studio|backdrop|seamless|photography set|cyclorama",
    "cafe": r"caf[eé]|coffee|restaurant|lobby|atrium|breakfast|bar\b|pub\b|diner|bakery|shop|store|boutique|mall|market|museum|gallery|cinema|theatre|theater",
    "office": r"office|meeting room|boardroom|classroom|school|university|campus",
    "gym": r"gym|fitness|workout|weight|yoga|pilates|dojo|boxing|locker",
    "pool": r"spa\b|pool|poolside|swimming|hot tub|jacuzzi|waterpark|lido",
    "beach": r"beach|sand\b|shore|seaside|coast|ocean|sea\b|surf|boardwalk|pier|dock|harbou?r|marina|yacht|boat|island|tropical|lagoon",
    "balcony": r"balcony|terrace|patio|veranda|porch|deck\b|rooftop|roof\b",
    "urban": r"street|city|urban|alley|crosswalk|downtown|neon|sidewalk|pavement|skyline|skyscraper|subway|station|"
             r"metro|tunnel|parking|graffiti|skate ?park|arcade|bus |taxi|train|airport|plaza|square\b|storefront",
    "nightlife": r"nightclub|nightlife|club\b|party|cocktail|late-night|lounge|bar\b|pub\b|festival|concert|stage|dance floor|vip|rave|karaoke|speakeasy",
    "nature": r"forest|woods|woodland|mountain|meadow|field|desert|countryside|hill|valley|lake|river|waterfall|canyon|"
              r"garden|park\b|farm|snow|jungle|cliff|trail|orchard|vineyard|cave|savanna|autumn|flower|sunset",
    "road": r"bridge|road|highway|garage|car park|gas station|petrol|drive-?in|motorway|driveway|truck|workshop|track\b|racetrack|showroom|parked",
    "industrial": r"warehouse|factory|abandoned|bunker|industrial|underground|basement|scrapyard|ruin|military|facility|laboratory|lab\b",
}
_PLACE_RX = {k: re.compile(chr(92) + "b(?:" + v + ")", re.I) for k, v in PLACE_WORDS.items()}

INDOOR = {"bedroom", "bathroom", "hotel", "home", "kitchen", "studio", "cafe", "office"}
OUTDOOR = {"balcony", "urban", "nature", "beach", "road", "industrial"}
PRIVATE = {"bedroom", "bathroom", "hotel", "home"}
# settings that clearly change the scene: rejected whenever mentioned and the action does not allow them
EXCLUSIVE = {"nightlife", "road", "industrial", "urban"}
ANY = None

# Action lists -> kinds of place that fit. Missing = any place fits.
ACTION_FITS = {
    "Bed": {"bedroom", "hotel", "home"},
    "Bedroom Glamour": {"bedroom", "hotel", "home"},
    "Morning Bedroom Scenes": {"bedroom", "hotel", "home"},
    "Bathroom and Vanity Scenes": {"bathroom", "hotel", "home"},
    "Shower and Bath": {"bathroom", "hotel", "home"},
    "Hotel": {"hotel", "bedroom", "balcony"},
    "Poolside": {"pool", "beach", "hotel", "balcony"},
    "Balcony": {"balcony", "hotel", "urban", "home"},
    "Chair": {"home", "hotel", "studio", "cafe", "office", "bedroom", "kitchen"},
    "Sofa": {"home", "hotel", "studio", "cafe", "bedroom"},
    "Floor": {"home", "hotel", "studio", "bedroom", "gym"},
    "Table Counter": {"home", "hotel", "cafe", "office", "studio", "kitchen"},
    "Staircase": {"home", "hotel", "urban", "studio", "office", "cafe"},
    "Stretching Poses": {"gym", "home", "studio", "nature", "beach", "bedroom"},
    "Gym Fit": {"gym", "studio", "nature", "beach"},
    "Yoga": {"gym", "home", "studio", "nature", "beach"},
    "Skater Girl": {"urban", "road"},
    "Vehicle Centerfold Poses": {"road", "urban", "industrial"},
    "Instagram Influencer": {"urban", "cafe", "home", "hotel", "balcony", "beach", "studio", "nature", "nightlife"},
}


@lru_cache(maxsize=None)
def places_in(text):
    """Kinds of place a text describes, in the order they are first mentioned (empty = no clear place)."""
    hits = []
    for kind, rx in _PLACE_RX.items():
        m = rx.search(text)
        if m:
            hits.append((m.start(), kind))
    return tuple(kind for _, kind in sorted(hits))


def allowed_places(collection_name, action_text=""):
    """Kinds of place that fit this action, or None when anything fits."""
    fits = ACTION_FITS.get(collection_name)
    cues = set(places_in(action_text)) - {"nightlife"}   # 'chaise lounge' in a pose is furniture, not a venue
    if cues & {"bedroom", "bathroom"}:
        cues |= {"hotel", "home"}
    if cues and fits:
        return (cues & fits) or (cues | fits)
    if cues:
        return cues
    return set(fits) if fits else None


def environment_fits(env_text, env_is_palette, allowed):
    """True when the environment's main (first-mentioned) kind of place is one the action allows."""
    if allowed is None:
        # a generic pose fits most places, but not a nightclub or a scenic road drive
        return env_is_palette or not (set(places_in(env_text)) & {"nightlife", "road"})
    if env_is_palette:
        return bool(allowed & INDOOR)
    found = places_in(env_text)
    if not found or found[0] not in allowed:
        return False
    # a strictly indoor pose (bed, bathroom...) should not land in a setting that is also a rooftop, street or beach
    kinds = set(found)
    if kinds & EXCLUSIVE - allowed:
        return False
    if allowed <= INDOOR and kinds & OUTDOOR:
        return False
    return not (allowed <= PRIVATE and kinds - PRIVATE)


# ---- clothing ---------------------------------------------------------------------------------------------------------
# What the woman is doing / where she is decides which clothing lists make sense.
# Lists in LOCKED only appear when the context calls for them; everything else is everyday wear and fits anywhere
# that has no special context.
ACTION_WEAR = {
    "Bed": "intimate", "Bedroom Glamour": "intimate", "Morning Bedroom Scenes": "intimate",
    "Bathroom and Vanity Scenes": "bathroom", "Shower and Bath": "bathroom", "Poolside": "water",
    "Gym Fit": "active", "Yoga": "active", "Stretching Poses": "active", "Skater Girl": "street",
}
PLACE_WEAR = {"bedroom": "intimate", "bathroom": "bathroom", "pool": "water", "beach": "water", "gym": "active"}

_INTIMATE = {"Bedroom Wear", "Lingerie", "Robes and Cover-ups", "Satin Robe Ensemble", "See Through Sheer",
             "Stockings and Hosiery", "Silk Slip Dress", "Lace Trimmed Camisole", "Satin Camisole", "Bodysuit",
             "Bustier Outfits", "Corsets", "Bardot Tops", "Rock and Metal Band Oversized Tees and Hoodies"}
WEAR_TAGS = {
    "intimate": _INTIMATE,
    "bathroom": {"Robes and Cover-ups", "Satin Robe Ensemble", "Bedroom Wear", "Lingerie", "Swimwear", "See Through Sheer",
                 "Bodysuit"},
    "water": {"Swimwear", "Beach Girl", "Summer Dresses", "Robes and Cover-ups", "Playsuits", "Rompers", "Bardot Tops",
              "Mini Dress", "Cutoutdress"},
    "active": {"Gym Fit", "Bodysuit"},
    "street": {"Skater Girl", "Streetwear", "Urban Street", "Alt Girl", "Goth Girl", "Instagram Influencer",
               "Mini Skirt Outfits", "Polo Shirts and Mini Skirts", "Bodysuit", "Jumpsuits",
               "Rock and Metal Band Oversized Tees and Hoodies"},
    "school": {"School Uniform Cosplay", "Polo Shirts and Mini Skirts", "Mini Skirt Outfits"},
    "gamer": {"Gamer Girl", "Streetwear", "Rock and Metal Band Oversized Tees and Hoodies"},
}
LOCKED = {"Bedroom Wear", "Lingerie", "Robes and Cover-ups", "Satin Robe Ensemble", "See Through Sheer", "Swimwear",
          "Beach Girl", "Gym Fit", "School Uniform Cosplay", "Gamer Girl"}
_SCHOOL_RX = re.compile(r"\b(?:school|classroom|campus|university)", re.I)
_GAMER_RX = re.compile(r"\b(?:gaming|gamer|arcade|esports)", re.I)


def wear_contexts(action_name, action_text, env_text):
    """(action-driven context, setting-driven contexts) for the clothing choice; either may be empty."""
    from_action = set()
    if action_name in ACTION_WEAR:
        from_action.add(ACTION_WEAR[action_name])
    for kind in places_in(action_text or ""):
        if kind in PLACE_WEAR:
            from_action.add(PLACE_WEAR[kind])
    from_env = set()
    found = places_in(env_text or "")
    if found and found[0] in PLACE_WEAR:
        from_env.add(PLACE_WEAR[found[0]])
    if _SCHOOL_RX.search(env_text or ""):
        from_env.add("school")
    if _GAMER_RX.search(env_text or ""):
        from_env.add("gamer")
    return from_action, from_env


def clothing_lists_allowed(all_names, action_name, action_text, env_text):
    """The clothing list names that suit this pose and setting."""
    from_action, from_env = wear_contexts(action_name, action_text, env_text)
    contexts = from_action | from_env
    if not contexts:
        return {n for n in all_names if n not in LOCKED}
    both = set(all_names)
    for ctx in contexts:
        both &= WEAR_TAGS[ctx]
    if both:
        return both
    # pose and setting disagree (e.g. a gym pose in a bedroom): the pose wins
    for group in (from_action, from_env):
        if group:
            pooled = set(all_names)
            for ctx in group:
                pooled &= WEAR_TAGS[ctx]
            return pooled or set().union(*(WEAR_TAGS[c] for c in group)) & set(all_names)
    return {n for n in all_names if n not in LOCKED}


# within a context, these lists are the natural choice and get picked more often than the general fits
WEAR_PRIMARY = {
    "intimate": {"Bedroom Wear", "Lingerie", "Robes and Cover-ups", "Satin Robe Ensemble", "Satin Camisole",
                 "Lace Trimmed Camisole", "Silk Slip Dress"},
    "bathroom": {"Robes and Cover-ups", "Satin Robe Ensemble", "Bedroom Wear", "Swimwear"},
    "water": {"Swimwear", "Beach Girl"},
    "active": {"Gym Fit"},
    "street": {"Skater Girl", "Streetwear", "Urban Street"},
    "school": {"School Uniform Cosplay"},
    "gamer": {"Gamer Girl"},
}
PRIMARY_BOOST = 3.0


def clothing_weights(all_names, action_name, action_text, env_text):
    """{clothing list name: weight multiplier} for the lists that suit this pose and setting."""
    names = clothing_lists_allowed(all_names, action_name, action_text, env_text)
    from_action, from_env = wear_contexts(action_name, action_text, env_text)
    contexts = from_action | from_env
    primary = set().union(*(WEAR_PRIMARY[c] for c in contexts)) if contexts else set()
    return {n: (PRIMARY_BOOST if n in primary else 1.0) for n in names}
