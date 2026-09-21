"""Turns chosen presets into the labelled-paragraph prompt structure. Pure text rules - no model involved."""
import json
import re

TITLES = {"subject": "Subject", "clothing": "Clothing", "action": "Action", "environment": "Environment",
          "camera": "Camera", "lighting": "Lighting", "style": "Style Details"}
SECTION_ORDER = ["subject", "clothing", "action", "environment", "camera", "lighting", "style"]

MASS_NOUNS = {"streetwear", "clothing", "lingerie", "sportswear", "loungewear", "swimwear", "activewear", "gymwear",
              "partywear", "resortwear", "homewear", "footwear", "eyewear", "outerwear", "knitwear", "formalwear",
              "photography", "lighting", "daylight", "sunlight", "moonlight", "firelight", "candlelight", "hair",
              "contact", "makeup", "skin", "lipstick", "eyeshadow", "eyeliner", "blush", "glow", "light", "illumination", "definition", "texture", "detail", "details"}
HAIR_COLOUR_WORDS = re.compile(
    r"\b(?:blonde?|brunette|chestnut|auburn|ginger|raven|platinum|silver|gr[ae]y|white|black|brown|red|copper|burgundy|"
    r"pink|blue|teal|purple|violet|lavender|green|mint|orange|honey|caramel|golden|strawberry|ash|jet)\b", re.I)
_ARTICLE_START = re.compile(r"(?:an?|the|some|several|two|three|both|no)\b", re.I)
_HEAD_CUT = re.compile(r"(?<![-\w])(?:with|featuring|paired|styled|worn|in|over|under|that|which|for|into|while|during|from|on|at|of|by|as|across|around|behind|toward|towards|against|through|beside|near|when|where)(?![-\w])"
                       r"|,|—|:", re.I)
_EYE_COLOUR_WORDS = (r"(?:brown|blue|green|hazel|amber|gr[ae]y|violet|purple|golden|gold|teal|turquoise|aqua|emerald|"
                     r"sapphire|honey|olive|cobalt|jade|pink|lilac|lavender|red|silver|ice|icy|steel|chocolate|caramel|cerulean)")
_EYE_COLOUR_RX = re.compile(
    r"\b" + _EYE_COLOUR_WORDS + r"(?:[- ][a-z]+){0,2}[- ]eyes?\b|\beye[- ]?colou?r|\b" + _EYE_COLOUR_WORDS + r"-eyed\b", re.I)
_WOMAN = re.compile(r"^(?:an? |the )?(?:(?:adult|young|beautiful|elegant|confident|stylish) )*woman\b\s*", re.I)


_WEARING_RX = re.compile(r"\b(?:wearing|wears|dressed in)\b", re.I)


def entry_mentions_clothing(entry):
    """True when a preset names garments of its own ('wearing a satin robe', 'slipping into a robe').

    Uses the clothing words found when the presets were imported, plus any 'wearing ...' phrasing. entry can be an entry
    dict or a database row: it needs 'text' and, optionally, 'mentions'."""
    try:
        raw = entry["mentions"]
    except (KeyError, IndexError):
        raw = None
    if raw:
        try:
            found = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            found = {}
        if isinstance(found, dict) and found.get("clothing"):
            return True
    return bool(_WEARING_RX.search(entry["text"]))


def guess_form(text):
    """How an entry is worded (same idea as the importer): 'woman_clause', 'she_clause', 'participial' or 'phrase'."""
    if _WOMAN.match(text):
        return "woman_clause"
    if re.match(r"(?:she|her)\b", text, re.I):
        return "she_clause"
    words = text.split()
    first = words[0] if words else ""
    return "participial" if first.lower().endswith("ing") and len(first) >= 5 else "phrase"


def mentions_eye_colour(text):
    """True when a text names the colour of the eyes ('blue eyes', 'amber-eyed', 'eye colour')."""
    return bool(_EYE_COLOUR_RX.search(text))


def article(text):
    return "an" if text[:1].lower() in "aeiou" else "a"


def lower_first(text):
    text = text.strip()
    first = text.split(" ", 1)[0]
    if not first[:1].isupper() or first.isupper() or any(ch.isdigit() for ch in first):
        return text
    return text[0].lower() + text[1:]


def sentence(text):
    text = text.strip().rstrip(".,;: ")
    return (text[:1].upper() + text[1:] + ".") if text else ""


def join_and(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def with_article(text):
    text = lower_first(text)
    if _ARTICLE_START.match(text):
        return text
    first, _, rest = text.partition(" ")
    words = [first] + _HEAD_CUT.split(rest, 1)[0].split()
    while len(words) > 1 and words[-1].lower() not in MASS_NOUNS and words[-1].lower().endswith(("ed", "ing", "ly")) and words[-2].lower() not in ("very", "and"):
        words.pop()
    last = words[-1].lower()
    plural = (re.search(r"\band\b", " ".join(words)) or (last.endswith("s") and not last.endswith(("ss", "us", "is")))
              or last in MASS_NOUNS or "hair" in [w.lower() for w in words])
    return text if plural else f"{article(text)} {text}"


def _is_participle(word):
    word = word.lower().strip(",")
    return (word.endswith(("ing", "ed")) and word not in ("red", "bed", "shed", "wed")
            or word in ("seated", "lying", "shown", "caught", "frozen", "seen", "held", "shot", "kept", "set"))


_LOCATION_WORDS = ("in", "on", "at", "beneath", "under", "beside", "near", "within", "against", "behind", "before", "inside",
                   "outside", "atop", "between", "among", "across", "over", "below")


def narrate(entry):
    """An entry that describes what the woman is doing, turned into a third-person sentence."""
    text = entry["text"].strip()
    m = _WOMAN.match(text)
    if m:
        rest = text[m.end():]
        words = rest.split()
        verb = next((w for w in words if not w.lower().endswith("ly")), "")
        if _is_participle(verb):
            return sentence("She is " + rest)
        if verb.lower().endswith("s") and not verb.lower().endswith("ss"):
            return sentence("She " + rest)
        if words and words[0].lower() == "with":
            return sentence("She has " + " ".join(words[1:]))
        if words and words[0].lower() in _LOCATION_WORDS:
            return sentence("She is " + rest)
        return sentence(text)
    if _is_participle(text.split()[0]):
        return sentence("She is " + lower_first(text))
    return sentence(text)


def _is_whole_scene(entry):
    return bool(entry["covers"]) or entry["tier"] == "scene"


def render_subject(entries):
    s = {e["slot"]: e["text"] for e in entries}
    age, skin, colour, eyes, style = s.get("age"), s.get("skin tone"), s.get("hair colour"), s.get("eye colour"), s.get("hair style")
    embed = bool(style and colour and colour.endswith(" hair") and " with " not in colour
                 and re.search(r"\bhair\b", style, re.I) and not HAIR_COLOUR_WORDS.search(style))
    inline, own = [], []
    for item in (skin, None if embed else colour, eyes):
        if item:
            (own if " with " in item else inline).append(item)
    parts = ["A woman" + (f" {age}" if age else "") + (f" with {join_and(inline)}" if inline else "") + "."]
    parts += [sentence("She has " + lower_first(x)) for x in own]
    if style and re.match(r"one side\b", style, re.I):
        parts.append(sentence(style))
    elif style and _WOMAN.match(style):
        parts.append(narrate({"text": style}))
    elif style and re.match(r"hair\s+\w+(?:ed|ing)\b", style, re.I):
        parts.append(sentence("Her hair is " + style.split(" ", 1)[1]))
    elif style:
        parts.append(sentence("She has " + with_article(re.sub(r"\bhair\b", colour, style, count=1, flags=re.I) if embed else style)))
    if s.get("body"):
        parts.append(sentence("She has " + with_article(s["body"])))
    size, shape = s.get("bust size"), s.get("bust shape")
    if size and shape:
        parts.append(sentence("She has " + with_article(size) + " with " + lower_first(shape)))
    elif size:
        parts.append(sentence("She has " + with_article(size)))
    elif shape:
        parts.append(sentence("She has breasts with " + lower_first(shape)))
    if s.get("makeup"):
        parts.append(sentence("She wears " + lower_first(s["makeup"])))
    if s.get("skin"):
        about_skin = re.match(r"(?:[\w-]+\s+){0,4}(?:skin|pores|complexion|freckles|texture|hands|face)", s["skin"], re.I)
        parts.append(sentence(("She has " + with_article(s["skin"])) if about_skin else s["skin"]))
    art = [lower_first(x) for x in (s.get("tattoos"), s.get("piercings")) if x]
    if art:
        parts.append(sentence("She has " + " and ".join(art)))
    expression = s.get("basic expression") or s.get("expression and eyes")
    if expression:
        text = lower_first(expression)
        first = next((w for w in text.lower().split() if not w.endswith("ly")), "")
        if first.endswith("ing"):
            parts.append(sentence("She is " + text))
        elif first in ("head", "eyes", "eye", "lips"):
            parts.append(sentence("Her " + text))
        else:
            parts.append(sentence("She has " + with_article(text)))
    return " ".join(parts)


_WEARING_LEAD = re.compile(
    r"^(?:(?:an?|the) )?(?:(?:adult|young|beautiful|elegant|confident|stylish) )*(?:woman|female|model|girl|lady|she)\s+"
    r"(?:is |are )?(?:wearing|dressed in|wears|in)\s+|^wearing\s+", re.I)


def render_clothing(entry):
    # some lists are written as 'Adult woman wearing a ...'; keep only the garments so 'She wears' reads once
    return sentence("She wears " + with_article(_WEARING_LEAD.sub("", entry["text"].strip(), count=1)))


def render_action(entry):
    return sentence(entry["text"]) if entry["slot"] == "adult scenes" else narrate(entry)


def render_environment(entry):
    text = entry["text"]
    if entry["form"] in ("woman_clause", "she_clause") or _is_whole_scene(entry):
        return narrate(entry)
    if entry["slot"] == "colour palette":
        return sentence("The interior uses a palette of " + lower_first(text))
    return sentence("The setting is " + with_article(text))


_IMPERATIVE = re.compile(r"^(?:frame|position|place|photograph|use|compose|crop|show|capture|keep|center|centre)\b", re.I)


def render_camera(entry):
    text, slot = lower_first(entry["text"]), entry["slot"]
    if _is_whole_scene(entry) or slot == "lens and film look":
        return sentence(entry["text"])
    if slot == "angle":
        return sentence("The image is captured with " + with_article(text))
    if re.match(r"frame (?:from|tightly)\b", text):
        return sentence(re.sub(r"^frame", "The shot is framed", text, count=1))
    if re.match(r"frame the\b", text):
        return sentence(re.sub(r"^frame", "The shot frames", text, count=1))
    if _IMPERATIVE.match(text):
        return sentence(entry["text"])
    if text.startswith("camera positioned"):
        return sentence("The camera is positioned" + text[len("camera positioned"):])
    if text.startswith("camera"):
        return sentence("The " + text)
    if text.startswith("entire"):
        return sentence("The shot shows the " + text)
    return sentence("The shot uses " + with_article(text))


def render_lighting(entry):
    if _is_whole_scene(entry):
        return sentence(entry["text"])
    text = lower_first(entry["text"])
    if _is_participle(text.split()[0]) or text.split()[0] in ("lit", "backlit", "candlelit"):
        return sentence("The scene is " + text)
    return sentence("The scene is lit by " + with_article(text))


def render_style(entry):
    if _is_whole_scene(entry) or entry["slot"] != "colour grading":
        return sentence(entry["text"])
    return sentence("The image has " + lower_first(entry["text"]))


RENDERERS = {"clothing": render_clothing, "action": render_action, "environment": render_environment,
             "camera": render_camera, "lighting": render_lighting, "style": render_style}


def compose(picks):
    """picks: {section: [entry dicts from db.get_entry]} -> the finished prompt text."""
    paragraphs = []
    for section in SECTION_ORDER:
        entries = picks.get(section)
        if not entries:
            continue
        body = render_subject(entries) if section == "subject" else RENDERERS[section](entries[0])
        if body:
            paragraphs.append(f"{TITLES[section]}: {body}")
    return "\n\n".join(paragraphs)
