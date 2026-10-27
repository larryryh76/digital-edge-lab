"""Structured scene specification, subject/action registry and validation.

This module is the single source of truth shared by:
  * src/pipeline.py   (planner, narration, QA orchestration)
  * src/blender_scene.py (renderer, running inside Blender's bundled Python)

It therefore uses the standard library only.

Design rule (this is the fix for run #73): the renderer never guesses a visual
treatment from free-text keywords. The planner must emit a *typed* scene: one
subject kind from SUBJECT_KINDS plus one action kind that the registry declares
as filmable for that subject. `template_id()` is then a pure, deterministic
function of those two fields, so the same specification can never produce two
different treatments, and the QA layer can assert exact expectations.
"""

from __future__ import annotations

SCHEMA_VERSION = 3
MIN_SCENES = 6
MAX_SCENES = 8
TARGET_WORDS = (80, 135)

BEAT_ROLES = ("hook", "setup", "escalate", "mechanism", "example", "reveal", "payoff")
CAMERA_FRAMINGS = ("extreme_close_up", "close_up", "medium", "wide")
CAMERA_MOVES = ("push_in", "pull_out", "pan_left", "pan_right", "orbit", "tilt_up", "static")
LIGHTING_MOODS = ("cool", "warm", "clinical", "dramatic")
ENVIRONMENTS = (
    "studio_plinth", "workbench", "chip_cavity", "open_terrain",
    "shelf_wall", "phone_bench", "clamp_rig", "grid_floor",
)
MATERIALS = ("glass", "metal", "ceramic", "emissive", "voxel", "stone")
COLORS = ("cyan", "gold", "steel", "navy", "copper", "ivory", "red")

# --- action registry -------------------------------------------------------
# `motion` is a machine-checkable requirement. The renderer measures the real
# animated values from Blender's evaluated dependency graph and reports them in
# the visual trace; QA compares measurement against requirement. One table
# drives the renderer, the trace contract and the QA gate.
ACTIONS = {
    "spin": {
        "summary": "subject rotates continuously about a visible axis",
        "motion": {"rotation_degrees_min": 120},
    },
    "compress": {
        "summary": "subject is visibly squashed down in scale",
        "motion": {"scale_ratio_max": 0.62},
    },
    "expand": {
        "summary": "subject grows in scale",
        "motion": {"scale_ratio_min": 1.45},
    },
    "squeeze": {
        "summary": "clamp jaws close and the subject deforms between them",
        "motion": {"translate_min": 0.55, "partner_part_moves": True,
                   "any_part_shrink_below": 0.80},
    },
    "descend": {
        "summary": "subject travels downward toward a target object",
        "motion": {"translate_down_min": 0.55},
    },
    "fall": {
        "summary": "subject drops and lands with a reaction",
        "motion": {"translate_down_min": 0.50},
    },
    "collide": {
        "summary": "two parts approach and make contact, second part reacts",
        "motion": {"translate_min": 0.45, "partner_part_moves": True},
    },
    "snap_to_grid": {
        "summary": "continuous subject snaps into discrete stepped positions",
        "motion": {"stepped_positions_min": 4, "rotation_degrees_min": 30},
    },
    "dissolve": {
        "summary": "parts shrink away until only the survivors remain",
        "motion": {"parts_removed_min": 2},
    },
    "collapse_to_one": {
        "summary": "several parallel parts merge into a single surviving part",
        "motion": {"parts_removed_min": 2, "translate_min": 0.30},
    },
    "assemble": {
        "summary": "separated parts converge into one aligned object",
        "motion": {"translate_min": 0.40, "parts_moved_min": 3},
    },
    "flow": {
        "summary": "packets travel along a path from one part to another",
        "motion": {"translate_min": 0.80},
    },
    "sweep": {
        "summary": "a scan beam travels across the subject leaving a highlight",
        "motion": {"translate_min": 0.90},
    },
    "scan": {
        "summary": "a lens or ring passes over the subject and reveals detail",
        "motion": {"translate_min": 0.60},
    },
    "reveal": {
        "summary": "an occluder moves aside to expose the subject",
        "motion": {"translate_min": 0.55, "partner_part_moves": True},
    },
    "transform": {
        "summary": "subject changes shape/scale into a second visible form",
        "motion": {"scale_ratio_max": 0.85, "partner_part_moves": True},
    },
    "pulse": {
        "summary": "emission and scale pulse outward in visible waves",
        "motion": {"scale_ratio_min": 1.18},
    },
    "compare_pan": {
        "summary": "camera pans between two distinguishable subjects that both move",
        "motion": {"translate_min": 0.25, "parts_moved_min": 2},
    },
}

# --- subject registry ------------------------------------------------------
# `parts` are the exact Blender object names the builder must create. The trace
# reports the objects it actually built, so QA can prove the requested subject
# was constructed instead of a generic stand-in.
SUBJECT_KINDS = {
    "glass_sphere": {
        "summary": "large translucent sphere with a glowing rim",
        "parts": ("sphere_core", "sphere_rim"),
        "actions": ("compress", "expand", "descend", "collide", "spin", "dissolve", "pulse", "sweep", "fall"),
        "keywords": ("sphere", "orb", "ball", "weights", "model"),
    },
    "metal_sphere": {
        "summary": "polished opaque sphere",
        "parts": ("sphere_core", "sphere_rim"),
        "actions": ("spin", "compress", "collide", "fall", "pulse", "sweep"),
        "keywords": ("sphere", "orb", "metal ball"),
    },
    "voxel_sphere": {
        "summary": "sphere approximated by discrete blocks",
        "parts": ("voxel_cell", "voxel_frame"),
        "actions": ("snap_to_grid", "assemble", "dissolve", "compress", "spin"),
        "keywords": ("voxel", "blocky", "grid", "quantized", "stepped"),
    },
    "dial": {
        "summary": "instrument dial with legible tick marks and a needle",
        "parts": ("dial_body", "dial_needle", "dial_ticks"),
        "actions": ("spin", "snap_to_grid", "sweep", "scan"),
        "keywords": ("dial", "gauge", "knob", "instrument", "precision"),
    },
    "clamp": {
        "summary": "two heavy jaws and a screw applying pressure",
        "parts": ("clamp_jaw_upper", "clamp_jaw_lower", "clamp_screw"),
        "actions": ("squeeze", "compress", "assemble"),
        "keywords": ("clamp", "vise", "press", "crusher"),
    },
    "smartphone": {
        "summary": "recognisable phone chassis with screen and camera notch",
        "parts": ("phone_chassis", "phone_screen", "phone_notch"),
        "actions": ("descend", "collide", "transform", "pulse", "reveal"),
        "keywords": ("phone", "smartphone", "mobile", "handset"),
    },
    "mountain_pair": {
        "summary": "two side-by-side terrain models, one smooth and one blocky",
        "parts": ("mountain_smooth", "mountain_voxel"),
        "actions": ("compare_pan", "transform", "reveal", "sweep"),
        "keywords": ("mountain", "terrain", "peak", "landscape"),
    },
    "pipe_bundle": {
        "summary": "parallel data pipes that can merge into a single stream",
        "parts": ("pipe_1", "pipe_2", "pipe_3", "pipe_4", "pipe_merged"),
        "actions": ("collapse_to_one", "flow", "dissolve"),
        "keywords": ("pipe", "conduit", "channel", "memory bus", "bandwidth"),
    },
    "chip_die": {
        "summary": "processor die with visible cores and traces",
        "parts": ("chip_substrate", "chip_core_a", "chip_core_b", "chip_core_c"),
        "actions": ("collapse_to_one", "flow", "pulse", "reveal"),
        "keywords": ("chip", "die", "processor", "silicon", "core"),
    },
    "weight_grid": {
        "summary": "ordered grid of numeric weights",
        "parts": ("weight_cell_a", "weight_cell_b", "weight_cell_c", "weight_cell_d"),
        "actions": ("snap_to_grid", "assemble", "compress", "flow"),
        "keywords": ("weights", "grid", "matrix", "numbers", "values"),
    },
    "block_pair": {
        "summary": "two labelled blocks connected (or not) by a link",
        "parts": ("block_a", "block_b", "block_link"),
        "actions": ("flow", "collide", "reveal", "assemble"),
        "keywords": ("two blocks", "relation", "link", "connection", "pair"),
    },
    "glass_slab": {
        "summary": "flat etched glass plates standing side by side",
        "parts": ("slab_left", "slab_right"),
        "actions": ("reveal", "collide", "transform"),
        "keywords": ("slab", "plate", "glass panel", "layer"),
    },
    "network_node": {
        "summary": "central node with radiating connections",
        "parts": ("node_core", "node_link_a", "node_link_b"),
        "actions": ("pulse", "flow", "expand"),
        "keywords": ("node", "network", "neuron", "connection"),
    },
    "bookshelf": {
        "summary": "shelved volumes with one hero book pulled out",
        "parts": ("shelf_frame", "book_hero"),
        "actions": ("reveal", "assemble", "scan"),
        "keywords": ("book", "library", "shelf", "volume"),
    },
    "compass": {
        "summary": "brass compass housing with a swinging needle",
        "parts": ("compass_body", "compass_needle"),
        "actions": ("spin", "reveal"),
        "keywords": ("compass", "needle", "direction"),
    },
    "lens": {
        "summary": "magnifying ring and glass that inspects the subject",
        "parts": ("lens_ring", "lens_glass"),
        "actions": ("scan", "sweep", "reveal"),
        "keywords": ("lens", "magnify", "inspect", "zoom"),
    },
    "balance_scale": {
        "summary": "two-pan balance that tips as weight moves",
        "parts": ("scale_beam", "scale_pan_left", "scale_pan_right"),
        "actions": ("compare_pan", "collide", "transform"),
        "keywords": ("scale", "balance", "weigh"),
    },
    "data_block": {
        "summary": "single chunky data block",
        "parts": ("block_core",),
        "actions": ("compress", "fall", "collide", "transform", "dissolve"),
        "keywords": ("block", "cube", "chunk", "data"),
    },
    "plinth_stack": {
        "summary": "stacked slabs on a plinth",
        "parts": ("plinth_base", "stack_lower", "stack_upper"),
        "actions": ("assemble", "fall", "collide"),
        "keywords": ("stack", "layers", "plinth", "tower"),
    },
    # Honest, clearly-labelled last resort. QA flags any episode that needs it.
    "generic_cube": {
        "summary": "neutral place-holder block (not an acceptable final visual)",
        "parts": ("cube_core",),
        "actions": ("spin", "compress"),
        "keywords": (),
    },
}

SUBJECT_ORDER = tuple(SUBJECT_KINDS)
FALLBACK_SUBJECT = "generic_cube"

# Per-scene measurable motion floor. A scene whose principal subject barely
# moves is a product failure regardless of what the metadata claims.
MIN_SUBJECT_DISPLACEMENT_UNITS = 0.18
MIN_SUBJECT_SCREEN_PIXELS = 10.0


class SpecError(ValueError):
    """Raised when a scene spec cannot be rendered honestly."""


def _require(condition, message):
    if not condition:
        raise SpecError(message)


def _as_text(value, field, allow_empty=False):
    if value is None:
        value = ""
    _require(isinstance(value, (str, int, float)) or value is None,
             f"{field} must be text")
    text = str(value).strip()
    if not allow_empty:
        _require(bool(text), f"{field} must not be empty")
    return text


def _one_of(value, allowed, field):
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    _require(text in allowed,
             f"{field}={text!r} is not one of {sorted(allowed)}")
    return text


def normalize_beats(beats):
    """Validate the script's narrative beats (the segmentation step)."""
    _require(isinstance(beats, list) and beats, "beats must be a non-empty list")
    _require(MIN_SCENES <= len(beats) <= MAX_SCENES,
             f"episode needs {MIN_SCENES}-{MAX_SCENES} beats, got {len(beats)}")
    out, seen = [], set()
    for i, beat in enumerate(beats):
        _require(isinstance(beat, dict), f"beat {i + 1} must be an object")
        beat_id = _as_text(beat.get("id") or f"b{i + 1}", f"beats[{i}].id")
        _require(beat_id not in seen, f"duplicate beat id {beat_id!r}")
        seen.add(beat_id)
        role = _one_of(beat.get("role", BEAT_ROLES[min(i, len(BEAT_ROLES) - 1)]),
                       BEAT_ROLES, f"beats[{i}].role")
        narration = _as_text(beat.get("narration"), f"beats[{i}].narration")
        words = len(narration.split())
        _require(6 <= words <= 42,
                 f"beat {beat_id} narration must be 6-42 words, got {words}")
        out.append({"id": beat_id, "role": role, "narration": narration})
    _require(out[0]["role"] == "hook", "the first beat must be the hook")
    _require(out[-1]["role"] == "payoff", "the last beat must be the payoff")
    roles = [b["role"] for b in out]
    _require(len(set(roles)) >= min(5, len(out)),
             "beats must escalate through distinct narrative roles")
    return out


def normalize_scene(scene, index, beat_ids):
    """Validate one scene and return the canonical typed specification."""
    _require(isinstance(scene, dict), f"scene {index + 1} must be an object")
    beat_id = _as_text(scene.get("beat_id"), f"scenes[{index}].beat_id")
    _require(beat_id in beat_ids, f"scene {index + 1} references unknown beat {beat_id!r}")

    subject_in = scene.get("subject") or {}
    _require(isinstance(subject_in, dict), f"scenes[{index}].subject must be an object")
    unit_kind = str(subject_in.get("kind", "")).strip().lower().replace(" ", "_").replace("-", "_")
    if unit_kind not in SUBJECT_KINDS:
        raise SpecError(
            f"scene {index + 1}: unsupported subject kind {subject_in.get('kind')!r}; "
            f"choose one of {sorted(SUBJECT_KINDS)}"
        )
    spec_subject = SUBJECT_KINDS[unit_kind]
    subject = {
        "kind": unit_kind,
        "label": _as_text(subject_in.get("label", ""), f"scenes[{index}].subject.label",
                          allow_empty=True),
        "material": _one_of(subject_in.get("material", "ceramic"), MATERIALS,
                            f"scenes[{index}].subject.material"),
        "color": _one_of(subject_in.get("color", "cyan"), COLORS,
                         f"scenes[{index}].subject.color"),
        "count": max(1, min(6, int(subject_in.get("count", 1) or 1))),
    }

    action_in = scene.get("action") or {}
    _require(isinstance(action_in, dict), f"scenes[{index}].action must be an object")
    action_kind = str(action_in.get("kind", "")).strip().lower().replace(" ", "_").replace("-", "_")
    if action_kind not in ACTIONS:
        raise SpecError(
            f"scene {index + 1}: unsupported action kind {action_in.get('kind')!r}; "
            f"choose one of {sorted(ACTIONS)}"
        )
    if action_kind not in spec_subject["actions"]:
        raise SpecError(
            f"scene {index + 1}: action {action_kind!r} is not filmable for subject "
            f"{unit_kind!r}; allowed: {list(spec_subject['actions'])}"
        )
    action = {
        "kind": action_kind,
        "intensity": _clamp_float(action_in.get("intensity", 0.7), 0.2, 1.0,
                                  f"scenes[{index}].action.intensity"),
    }

    env_in = scene.get("environment") or {}
    _require(isinstance(env_in, dict), f"scenes[{index}].environment must be an object")
    environment = {
        "kind": _one_of(env_in.get("kind", "studio_plinth"), ENVIRONMENTS,
                        f"scenes[{index}].environment.kind"),
        "props": [str(p) for p in (env_in.get("props") or [])][:4],
    }

    camera_in = scene.get("camera") or {}
    _require(isinstance(camera_in, dict), f"scenes[{index}].camera must be an object")
    camera = {
        "framing": _one_of(camera_in.get("framing", "medium"), CAMERA_FRAMINGS,
                           f"scenes[{index}].camera.framing"),
        "move": _one_of(camera_in.get("move", "push_in"), CAMERA_MOVES,
                        f"scenes[{index}].camera.move"),
    }

    lighting_in = scene.get("lighting") or {}
    _require(isinstance(lighting_in, dict), f"scenes[{index}].lighting must be an object")
    lighting = {
        "mood": _one_of(lighting_in.get("mood", "cool"), LIGHTING_MOODS,
                        f"scenes[{index}].lighting.mood"),
    }

    on_screen = _as_text(scene.get("on_screen_text", ""),
                         f"scenes[{index}].on_screen_text", allow_empty=True)
    _require(len(on_screen.split()) <= 5,
             f"scene {index + 1}: on_screen_text must be at most 5 words")

    qa_in = scene.get("qa") or {}
    _require(isinstance(qa_in, dict), f"scenes[{index}].qa must be an object")
    must_show = [str(x) for x in (qa_in.get("must_show") or [])][:8]
    must_change = [str(x) for x in (qa_in.get("must_change") or [])][:6]
    if not must_show:
        must_show = [subject["kind"].replace("_", " ")]
        if subject["label"]:
            must_show.append(subject["label"])
    if not must_change:
        must_change = [ACTIONS[action_kind]["summary"]]

    return {
        "index": index,
        "beat_id": beat_id,
        "subject": subject,
        "action": action,
        "environment": environment,
        "camera": camera,
        "lighting": lighting,
        "from_state": _as_text(scene.get("from_state", ""),
                               f"scenes[{index}].from_state", allow_empty=True),
        "to_state": _as_text(scene.get("to_state", ""),
                             f"scenes[{index}].to_state", allow_empty=True),
        "on_screen_text": on_screen,
        "qa": {"must_show": must_show, "must_change": must_change},
        "degraded": bool(scene.get("degraded", False)),
    }


def _clamp_float(value, low, high, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{field} must be numeric") from exc
    if number != number:  # NaN
        raise SpecError(f"{field} must be numeric")
    return round(max(low, min(high, number)), 3)


def normalize_episode(data):
    """Normalise a full episode plan and return (episode, errors).

    `errors` is empty when the plan is fully renderable. When non-empty the
    caller must repair the plan; nothing is ever rendered from an invalid plan.
    """
    errors = []
    if not isinstance(data, dict):
        return None, ["episode plan must be a JSON object"]
    for field in ("title", "description", "topic", "sources", "hashtags"):
        if not data.get(field):
            errors.append(f"missing {field}")
    try:
        beats = normalize_beats(data.get("beats"))
    except SpecError as exc:
        return None, errors + [str(exc)]
    beat_ids = {b["id"] for b in beats}

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list):
        return None, errors + ["scenes must be a list"]
    if len(raw_scenes) != len(beats):
        return None, errors + [
            f"scenes ({len(raw_scenes)}) must match beats ({len(beats)}) one-to-one"
        ]

    scenes, used_beats = [], set()
    for i, raw in enumerate(raw_scenes):
        try:
            scene = normalize_scene(raw, i, beat_ids)
        except SpecError as exc:
            errors.append(str(exc))
            continue
        if scene["beat_id"] in used_beats:
            errors.append(f"beat {scene['beat_id']} is used by more than one scene")
            continue
        used_beats.add(scene["beat_id"])
        scenes.append(scene)
    if errors:
        return None, errors

    used_subjects = [s["subject"]["kind"] for s in scenes]
    used_actions = [s["action"]["kind"] for s in scenes]
    if len(set(used_subjects)) < max(3, len(scenes) - 2):
        errors.append(
            "visual subjects are not varied enough: "
            f"{used_subjects} must use at least {max(3, len(scenes) - 2)} distinct subjects"
        )
    if len(set(used_actions)) < max(3, len(scenes) - 3):
        errors.append(
            "visual actions are not varied enough: "
            f"{used_actions} must use at least {max(3, len(scenes) - 3)} distinct actions"
        )
    if any(s["subject"]["kind"] == FALLBACK_SUBJECT for s in scenes):
        errors.append(
            f"{FALLBACK_SUBJECT} is a place-holder subject and may not appear in a delivery"
        )
    if errors:
        return None, errors

    episode = {
        "schema_version": SCHEMA_VERSION,
        "title": _as_text(data.get("title"), "title"),
        "description": _as_text(data.get("description"), "description"),
        "topic": _as_text(data.get("topic"), "topic"),
        "hashtags": [str(t) for t in (data.get("hashtags") or [])][:10],
        "sources": _normalize_sources(data.get("sources")),
        "beats": beats,
        "scenes": scenes,
        "narration": " ".join(b["narration"] for b in beats),
        "origin": str(data.get("origin", "generated")),
    }
    word_count = len(episode["narration"].split())
    if not (TARGET_WORDS[0] <= word_count <= TARGET_WORDS[1]):
        errors.append(
            f"narration is {word_count} words; must be {TARGET_WORDS[0]}-{TARGET_WORDS[1]}"
        )
    if errors:
        return None, errors
    return episode, []


def _normalize_sources(sources):
    out = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        out.append({
            "name": str(source.get("name", "")).strip(),
            "url": str(source.get("url", "")).strip(),
            "supports": str(source.get("supports", "")).strip(),
        })
    return out[:6]


# --- deterministic dispatch ------------------------------------------------

def template_id(scene):
    """Deterministic renderer template for a validated scene. No text matching."""
    return f"{scene['subject']['kind']}__{scene['action']['kind']}"


def required_parts(scene):
    """Object names the renderer must create for this scene."""
    return list(SUBJECT_KINDS[scene["subject"]["kind"]]["parts"])


def motion_requirement(scene):
    """Machine-checkable motion requirement for the scene's action."""
    base = dict(ACTIONS[scene["action"]["kind"]]["motion"])
    base.setdefault("subject_displacement_min", MIN_SUBJECT_DISPLACEMENT_UNITS)
    base["subject_screen_pixels_min"] = MIN_SUBJECT_SCREEN_PIXELS
    return base


def fallback_action(subject_kind):
    """Deterministic primary action for a subject kind (repair path)."""
    return SUBJECT_KINDS[subject_kind]["actions"][0]


def nearest_subject(text):
    """Deterministic keyword mapping used only to repair an unsupported kind.

    This is *not* the treatment selection path: it is used to coerce an
    unrenderable plan back onto the closest supported subject so the episode
    fails loudly with a usable diagnostic instead of silently rendering an
    unrelated object.
    """
    low = str(text or "").lower()
    best, best_score = FALLBACK_SUBJECT, 0
    for kind, meta in SUBJECT_KINDS.items():
        score = sum(1 for word in meta["keywords"] if word in low)
        if score > best_score:
            best, best_score = kind, score
    return best
