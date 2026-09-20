"""Best-effort extraction of prompt/negative/seed/model/LoRAs/sampler
settings from a ComfyUI-generated PNG's embedded metadata.

ComfyUI embeds two PNG text chunks: 'prompt' (the actual executed API-format
graph - {node_id: {class_type, inputs}}) and 'workflow' (the UI-format graph
for reopening in the editor). This reads 'prompt', since that's what was
actually run.

ComfyUI graphs vary hugely between custom node packs, so this can't be a
universal solver - it handles the standard node types (CheckpointLoaderSimple,
CLIPTextEncode, KSampler/KSamplerAdvanced, LoraLoader) plus common rgthree nodes
(Context Big's passthrough-bundle pattern, Power Lora Loader, Seed). Anything it
can't resolve is just omitted from the structured view - the full raw JSON is
always available as a fallback (see analyser_tab.py's Raw tab).
"""

import json
import re

from app.png_metadata import read_png_text_chunks

_INLINE_LORA_RE = re.compile(r"<lora:([^:>]+):([^>]+)>", re.IGNORECASE)

CONTEXT_NODE_TYPES = {"Context Big (rgthree)", "Context (rgthree)", "Context Small (rgthree)"}

# rgthree's Context/Context Big nodes bundle many values through one wire;
# an output slot's value comes from the same-named input if that node set
# it, otherwise from its base_ctx (chained from an upstream Context node) -
# see the mapping below, reverse-engineered from a real Context Big node's
# actual input/output list (both always in this fixed order).
CONTEXT_OUTPUT_TO_INPUT_KEY = {
    1: "model", 2: "clip", 3: "vae", 4: "positive", 5: "negative", 6: "latent",
    7: "images", 8: "seed", 9: "steps", 10: "step_refiner", 11: "cfg",
    12: "ckpt_name", 13: "sampler", 14: "scheduler", 15: "clip_width",
    16: "clip_height", 17: "text_pos_g", 18: "text_pos_l", 19: "text_neg_g",
    20: "text_neg_l", 21: "mask", 22: "control_net",
}

TEXT_LEAF_TYPES = {
    "CLIPTextEncode": "text",
    "CLIPTextEncodeSDXL": "text_g",
    "PrimitiveStringMultiline": "value",
    "PrimitiveString": "value",
    "String Literal": "text",
    "Text Multiline": "text",
}

CHECKPOINT_LOADER_TYPES = {
    "CheckpointLoaderSimple": "ckpt_name",
    "UNETLoader": "unet_name",
    "CheckpointLoader": "ckpt_name",
}

LORA_LOADER_TYPES = {"LoraLoader", "LoraLoaderModelOnly", "LoraLoader|pysssss"}

SEED_NODE_TYPES = {"Seed (rgthree)": "seed"}

# Conditioning-transformer nodes: same output index maps to a specific input
# key, no chaining needed (unlike Context nodes' base_ctx fallback).
CONDITIONING_PASSTHROUGH_TYPES = {
    "InpaintModelConditioning": {0: "positive", 1: "negative"},
}

# Node types whose output is deliberately empty/non-textual - following
# through to their input would find real text, but it would misrepresent
# what's actually happening. ConditioningZeroOut is standard practice on
# Flux workflows (Flux doesn't use a real negative prompt; this node zeroes
# the conditioning out rather than encoding different text).
NULL_CONDITIONING_TYPES = {"ConditioningZeroOut"}


def _is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


def resolve(graph, value, seen=None):
    """Resolves a graph value that may be a literal, or a [node_id, output_index]
    link that needs following through zero or more intermediate nodes."""
    if not _is_link(value):
        return value
    seen = seen if seen is not None else set()
    node_id, output_index = value
    if node_id in seen or node_id not in graph:
        return None
    seen = seen | {node_id}
    node = graph[node_id]
    class_type = node.get("class_type", "")
    inputs = node.get("inputs", {})

    if class_type in NULL_CONDITIONING_TYPES:
        return None

    if class_type in CONTEXT_NODE_TYPES:
        input_key = CONTEXT_OUTPUT_TO_INPUT_KEY.get(output_index)
        if input_key is None:
            return None
        return _resolve_context_field(graph, node_id, input_key, seen)

    if class_type in CONDITIONING_PASSTHROUGH_TYPES:
        input_key = CONDITIONING_PASSTHROUGH_TYPES[class_type].get(output_index)
        if input_key is None:
            return None
        return resolve(graph, inputs.get(input_key), seen)

    if class_type in TEXT_LEAF_TYPES:
        return resolve(graph, inputs.get(TEXT_LEAF_TYPES[class_type]), seen)

    if class_type in SEED_NODE_TYPES:
        return resolve(graph, inputs.get(SEED_NODE_TYPES[class_type]), seen)

    # Generic single-link passthrough (reroutes and similar utility nodes):
    # if exactly one input is wired to another node, follow it.
    link_inputs = [v for v in inputs.values() if _is_link(v)]
    if len(link_inputs) == 1:
        return resolve(graph, link_inputs[0], seen)

    return None


def _resolve_context_field(graph, node_id, input_key, seen):
    node = graph.get(node_id)
    if node is None:
        return None
    inputs = node.get("inputs", {})
    value = inputs.get(input_key)
    if value is not None:
        return resolve(graph, value, seen)
    base_ctx = inputs.get("base_ctx")
    if _is_link(base_ctx):
        return _resolve_context_field(graph, base_ctx[0], input_key, seen | {node_id})
    return None


def _find_sampler_node(graph):
    """A node is treated as 'the sampler' if it has positive+negative
    conditioning wired AND a seed/steps input - true across virtually every
    ComfyUI sampler node regardless of custom-node origin, unlike matching
    on class_type name (which varies a lot: KSampler, KSamplerAdvanced,
    ClownsharKSampler_Beta, SamplerCustom, ...). positive+negative alone
    isn't specific enough - conditioning-combiner nodes like
    InpaintModelConditioning have both but aren't the sampler."""
    for node_id, node in graph.items():
        inputs = node.get("inputs", {})
        has_cond = _is_link(inputs.get("positive")) and _is_link(inputs.get("negative"))
        has_seed = "seed" in inputs or "noise_seed" in inputs
        has_steps = "steps" in inputs
        if has_cond and has_seed and has_steps:
            return node_id, node
    return None, None


def _find_first(graph, types_map):
    for node in graph.values():
        if node.get("class_type") in types_map:
            return node
    return None


def _extract_loras(graph):
    loras = []
    for node in graph.values():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        if class_type in LORA_LOADER_TYPES:
            name = inputs.get("lora_name")
            strength = inputs.get("strength_model", inputs.get("strength"))
            if name:
                loras.append(f"{name} ({strength})" if strength is not None else str(name))
        elif class_type == "Power Lora Loader (rgthree)":
            for key, entry in inputs.items():
                if key.startswith("lora_") and isinstance(entry, dict) and entry.get("on") and entry.get("lora"):
                    strength = entry.get("strength")
                    loras.append(f"{entry['lora']} ({strength})" if strength is not None else entry["lora"])
    return loras


def extract_comfyui_metadata(graph):
    """graph: the parsed 'prompt' chunk JSON. Returns a dict of whatever
    fields could be resolved - missing fields are simply absent, callers
    should treat every key as optional."""
    result = {}

    sampler_id, sampler_node = _find_sampler_node(graph)
    if sampler_node:
        inputs = sampler_node["inputs"]
        positive_text = resolve(graph, inputs.get("positive"))
        negative_text = resolve(graph, inputs.get("negative"))
        if isinstance(positive_text, str):
            result["prompt"] = positive_text
        if isinstance(negative_text, str):
            result["negative_prompt"] = negative_text

        seed = inputs.get("seed", inputs.get("noise_seed"))
        seed = resolve(graph, seed) if _is_link(seed) else seed
        if seed is not None:
            result["seed"] = seed

        for field, keys in (
            ("steps", ("steps",)),
            ("cfg", ("cfg",)),
            ("sampler", ("sampler_name", "sampler")),
            ("scheduler", ("scheduler",)),
            ("denoise", ("denoise",)),
        ):
            for key in keys:
                if key in inputs:
                    value = resolve(graph, inputs[key]) if _is_link(inputs[key]) else inputs[key]
                    if value is not None:
                        result[field] = value
                    break

    if "prompt" not in result:
        for node in graph.values():
            if node.get("class_type") in TEXT_LEAF_TYPES:
                key = TEXT_LEAF_TYPES[node["class_type"]]
                text = node.get("inputs", {}).get(key)
                if isinstance(text, str) and text.strip():
                    result.setdefault("prompt", text)
                    break

    ckpt_node = _find_first(graph, CHECKPOINT_LOADER_TYPES)
    if ckpt_node:
        key = CHECKPOINT_LOADER_TYPES[ckpt_node["class_type"]]
        name = ckpt_node.get("inputs", {}).get(key)
        if isinstance(name, str):
            result["model"] = name

    loras = _extract_loras(graph)
    if loras:
        result["loras"] = loras

    return result


def parse_a1111_parameters(text):
    """Fallback for images not from ComfyUI: the standard A1111-family
    'parameters' text chunk - a prompt, optional 'Negative prompt:' line,
    then a comma-separated 'Steps: N, Sampler: X, CFG scale: Y, Seed: Z, ...'
    settings line."""
    result = {}
    if not text:
        return result

    negative_marker = "\nNegative prompt:"
    if negative_marker in text:
        prompt_part, rest = text.split(negative_marker, 1)
    else:
        prompt_part, rest = text, ""

    lines = rest.split("\n", 1)
    negative_part = lines[0].strip() if lines else ""
    settings_part = lines[1] if len(lines) > 1 else ""
    if not settings_part:
        # Settings line is often the last line of prompt_part when there's
        # no negative prompt at all.
        prompt_lines = prompt_part.rsplit("\n", 1)
        if len(prompt_lines) == 2 and re_looks_like_settings(prompt_lines[1]):
            prompt_part, settings_part = prompt_lines

    result["prompt"] = prompt_part.strip()
    if negative_part:
        result["negative_prompt"] = negative_part

    inline_loras = [f"{name}:{weight}" for name, weight in _INLINE_LORA_RE.findall(prompt_part)]
    if inline_loras:
        result["loras"] = inline_loras

    for pair in settings_part.split(","):
        if ":" not in pair:
            continue
        key, _, value = pair.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "steps":
            result["steps"] = value
        elif key == "cfg scale":
            result["cfg"] = value
        elif key == "sampler":
            result["sampler"] = value
        elif key == "schedule type":
            result["scheduler"] = value
        elif key == "seed":
            result["seed"] = value
        elif key == "model":
            result["model"] = value

    return result


def re_looks_like_settings(line):
    return "Steps:" in line and "Seed:" in line


def extract_metadata(image_path):
    """Reads a PNG's embedded metadata and returns (structured_dict, raw_text,
    source). source is 'comfyui', 'a1111', or None if nothing recognizable
    was found. structured_dict fields (all optional): prompt, negative_prompt,
    seed, model, loras, steps, cfg, sampler, scheduler, denoise."""
    chunks = read_png_text_chunks(image_path)

    if "prompt" in chunks:
        try:
            graph = json.loads(chunks["prompt"])
            structured = extract_comfyui_metadata(graph)
            return structured, chunks["prompt"], "comfyui"
        except (json.JSONDecodeError, TypeError):
            pass

    if "parameters" in chunks:
        structured = parse_a1111_parameters(chunks["parameters"])
        return structured, chunks["parameters"], "a1111"

    return {}, "", None
