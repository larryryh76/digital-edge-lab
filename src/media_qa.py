"""Deterministic QA over the rendered media (not over intended metadata).

Everything here is measured from the encoded files with ffprobe/ffmpeg plus the
renderer's own measured animation trace. A scene passes only when the subject
that was requested is present in the trace, the action's measurable motion
requirement is met by real animated transforms, and the encoded pixels show
motion that is not merely a frozen frame.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path


MOTION_FLOOR = 0.45
HERO_BOX = {"x": 180, "y": 300, "w": 360, "h": 520}
BACKGROUND_BOX = {"x": 0, "y": 0, "w": 200, "h": 200}


def _run(argv, timeout=90):
    return subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)


def probe(path):
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,format_name:"
        "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration,"
        "nb_frames,sample_rate,channels,display_aspect_ratio",
        "-of", "json", str(path),
    ])
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-400:]}")
    return json.loads(result.stdout)


def video_stream(info):
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)


def audio_stream(info):
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)


def frame_count(path):
    info = probe(path)
    stream = video_stream(info) or {}
    try:
        return int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        return 0


def _luma_differences(path, crop=None):
    """Per-frame mean luminance difference: a direct measure of visible change."""
    filters = []
    if crop:
        filters.append(f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}")
    filters.extend(["tblend=all_mode=difference", "signalstats",
                    "metadata=print:key=lavfi.signalstats.YAVG:file=-"])
    result = _run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", ",".join(filters),
                   "-an", "-f", "null", "-"], timeout=180)
    values = [float(v) for v in re.findall(r"YAVG=([\d.]+)", result.stdout + result.stderr)]
    return values


def motion_stats(path):
    values = _luma_differences(path)
    if not values:
        return {"frames": 0, "mean": 0.0, "max": 0.0, "min": 0.0, "static_fraction": 1.0}
    static = sum(1 for v in values if v < 0.08)
    return {
        "frames": len(values),
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "static_fraction": round(static / len(values), 3),
    }


def region_motion(path, box):
    values = _luma_differences(path, crop=box)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def black_segments(path, min_duration=0.2, threshold=0.90):
    result = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                   "-vf", f"blackdetect=d={min_duration}:pic_th={threshold}:pix_th=0.06",
                   "-an", "-f", "null", "-"], timeout=180)
    return re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", result.stderr)


def frozen_segments(path, noise_db=-50, min_duration=0.7):
    result = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                   "-vf", f"freezedetect=n={noise_db}dB:d={min_duration}",
                   "-an", "-f", "null", "-"], timeout=180)
    starts = [float(v) for v in re.findall(r"freeze_start: ([\d.]+)", result.stderr)]
    durations = [float(v) for v in re.findall(r"freeze_duration: ([\d.]+)", result.stderr)]
    total = _duration(path)
    out = []
    for i, start in enumerate(starts):
        if i < len(durations):
            out.append((start, durations[i]))
        else:
            # A freeze that runs to the end of the clip is still a freeze.
            out.append((start, max(0.0, total - start)))
    return out


def audio_levels(path):
    result = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                   "-af", "volumedetect", "-f", "null", "-"], timeout=120)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    return {
        "mean_db": float(mean.group(1)) if mean else None,
        "peak_db": float(peak.group(1)) if peak else None,
    }


def silence_segments(path, threshold=-42, min_duration=0.9):
    result = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                   "-af", f"silencedetect=n={threshold}dB:d={min_duration}",
                   "-f", "null", "-"], timeout=120)
    starts = re.findall(r"silence_start: (-?[\d.]+)", result.stderr)
    ends = re.findall(r"silence_end: (-?[\d.]+)", result.stderr)
    return [(float(a), float(b)) for a, b in zip(starts, ends)]


def extract_frame(path, seconds, out_path, width=720, height=1280):
    result = _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, seconds):.3f}",
                   "-i", str(path), "-frames:v", "1",
                   "-vf", f"scale={width}:{height}", str(out_path)], timeout=60)
    if result.returncode or not Path(out_path).exists():
        raise RuntimeError(f"could not extract frame at {seconds:.2f}s from {path}")
    return out_path


def image_similarity(path_a, path_b):
    """SSIM between two still frames (1.0 = identical)."""
    result = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path_a), "-i", str(path_b),
                   "-lavfi", "ssim", "-f", "null", "-"], timeout=90)
    match = re.search(r"All:([\d.]+)", result.stderr)
    return float(match.group(1)) if match else 0.0


def contact_sheet(path, out_path, columns=4, rows=4, tile_width=180, tile_height=320):
    result = _run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf",
                   f"fps=1/{max(1.0, _duration(path) / (columns * rows)):.3f},"
                   f"scale={tile_width}:{tile_height},"
                   f"tile={columns}x{rows}:padding=4:color=black",
                   "-frames:v", "1", str(out_path)], timeout=180)
    if result.returncode or not Path(out_path).exists():
        raise RuntimeError(f"contact sheet failed: {result.stderr[-300:]}")
    return out_path


def _duration(path):
    info = probe(path)
    return float(info.get("format", {}).get("duration", 0.0) or 0.0)


# --- requirement comparison -------------------------------------------------
def compare_motion(requirement, measured, part_measurements=None):
    """Return (passed, failures[]) comparing measured animation to requirement."""
    failures = []
    part_measurements = part_measurements or {}

    if "rotation_degrees_min" in requirement:
        value = measured.get("rotation_degrees", 0.0)
        if value < requirement["rotation_degrees_min"]:
            failures.append(
                f"rotation {value:.1f}deg < required {requirement['rotation_degrees_min']}deg")
    if "scale_ratio_max" in requirement:
        value = measured.get("scale_ratio_min", 1.0)
        if value > requirement["scale_ratio_max"]:
            failures.append(
                f"shrink ratio {value:.2f} > allowed {requirement['scale_ratio_max']}")
    if "scale_ratio_min" in requirement:
        value = measured.get("scale_ratio_max", 1.0)
        if value < requirement["scale_ratio_min"]:
            failures.append(
                f"growth ratio {value:.2f} < required {requirement['scale_ratio_min']}")
    if "translate_down_min" in requirement:
        value = measured.get("translate_down", 0.0)
        if value < requirement["translate_down_min"]:
            failures.append(
                f"downward travel {value:.2f} < required {requirement['translate_down_min']}")
    if "translate_min" in requirement:
        value = measured.get("displacement", 0.0)
        if value < requirement["translate_min"]:
            failures.append(
                f"travel {value:.2f} < required {requirement['translate_min']}")
    if "parts_moved_min" in requirement:
        value = measured.get("parts_moved", 0)
        if value < requirement["parts_moved_min"]:
            failures.append(
                f"only {value} parts moved, required {requirement['parts_moved_min']}")
    if "parts_removed_min" in requirement:
        value = measured.get("parts_removed", 0)
        if value < requirement["parts_removed_min"]:
            failures.append(
                f"only {value} parts disappeared, required {requirement['parts_removed_min']}")
    if "stepped_positions_min" in requirement:
        value = measured.get("distinct_positions", 0)
        if value < requirement["stepped_positions_min"]:
            failures.append(
                f"{value} distinct positions < required {requirement['stepped_positions_min']}")
    if requirement.get("partner_part_moves"):
        moved = measured.get("moving_part_names") or []
        if not moved:
            failures.append("no secondary part moved (interaction not visible)")
    if "any_part_shrink_below" in requirement:
        limit = requirement["any_part_shrink_below"]
        ratios = [p.get("scale_ratio_min", 1.0) for p in part_measurements.values()]
        if not ratios or min(ratios) > limit:
            failures.append(
                f"no part was visibly deformed (best shrink ratio "
                f"{min(ratios) if ratios else 1.0:.2f} > allowed {limit})")
    if "any_part_height_shrink_below" in requirement:
        limit = requirement["any_part_height_shrink_below"]
        ratios = [p.get("height_ratio_min", 1.0) for p in part_measurements.values()]
        if not ratios or min(ratios) > limit:
            failures.append(
                f"nothing was flattened (best height ratio "
                f"{min(ratios) if ratios else 1.0:.2f} > allowed {limit})")

    floor = requirement.get("subject_displacement_min", 0.0)
    if measured.get("displacement", 0.0) < floor:
        failures.append(
            f"subject displacement {measured.get('displacement', 0.0):.3f} "
            f"< floor {floor}")
    screen_floor = requirement.get("subject_screen_pixels_min", 0.0)
    if measured.get("screen_pixels", 0.0) < screen_floor:
        failures.append(
            f"subject screen travel {measured.get('screen_pixels', 0.0):.1f}px "
            f"< floor {screen_floor}px")
    return (not failures), failures


class SceneReport(dict):
    pass


def evaluate_scene(scene, window, segment_path, trace, spec_module):
    """Full per-scene gate: subject presence, measured motion, encoded motion."""
    failures, warnings = [], []
    required = set(trace.get("required_parts") or [])
    built = set(trace.get("built_parts") or [])
    missing = sorted(required - built)
    if missing:
        failures.append(f"requested subject parts missing from render: {missing}")
    expected_template = spec_module.template_id(scene)
    if trace.get("template") != expected_template:
        failures.append(
            f"renderer template {trace.get('template')!r} != specified {expected_template!r}")

    measured = dict(trace.get("measured", {}).get("mover", {}))
    measured["parts_moved"] = trace.get("measured", {}).get("parts_moved", 0)
    measured["parts_removed"] = trace.get("measured", {}).get("parts_removed", 0)
    measured["moving_part_names"] = trace.get("measured", {}).get("moving_part_names", [])
    requirement = trace.get("requirement") or spec_module.motion_requirement(scene)
    part_measurements = dict(trace.get("measured", {}).get("parts") or {})
    squeezed = trace.get("measured", {}).get("squeezed_part")
    if squeezed:
        part_measurements["_squeezed"] = squeezed
    motion_ok, motion_failures = compare_motion(requirement, measured, part_measurements)
    failures.extend(motion_failures)

    hero = trace.get("measured", {}).get("hero", {}) or {}
    hero_energy = background_energy = 0.0
    stats = {"frames": 0, "mean": 0.0, "max": 0.0, "min": 0.0, "static_fraction": 1.0}
    if not Path(segment_path).exists():
        failures.append(f"encoded segment missing: {segment_path}")
    else:
        stats = motion_stats(segment_path)
        if stats["frames"] < 5:
            failures.append(f"segment has only {stats['frames']} decodable frames")
        if stats["mean"] < MOTION_FLOOR:
            failures.append(f"rendered motion energy {stats['mean']:.3f} is below the "
                            f"{MOTION_FLOOR} floor (scene looks static)")
        if stats["static_fraction"] > 0.55:
            failures.append(f"{stats['static_fraction']:.0%} of frames are effectively "
                            f"unchanged")
        frozen = frozen_segments(segment_path)
        if frozen:
            failures.append(
                "frozen intervals detected at "
                + str([f"{round(a, 2)}s+{round(d, 2)}s" for a, d in frozen[:3]]))
        black = black_segments(segment_path)
        if black:
            failures.append(f"black frames detected from {black[0][0]}s to {black[0][1]}s")

        # Subject-driven motion must dominate the background region.
        hero_energy = region_motion(segment_path, HERO_BOX)
        background_energy = region_motion(segment_path, BACKGROUND_BOX)
        dominates = hero_energy >= max(0.10, background_energy * 0.75)
        if not dominates and hero.get("screen_pixels", 0.0) < 24.0:
            failures.append(
                f"centre motion {hero_energy:.3f} does not dominate background "
                f"{background_energy:.3f} and the subject moved only "
                f"{hero.get('screen_pixels', 0.0):.1f}px on screen (camera-only motion)")

    return {
        "scene_index": scene["index"],
        "beat_id": scene["beat_id"],
        "template": trace.get("template"),
        "subject": scene["subject"]["kind"],
        "action": scene["action"]["kind"],
        "window": {"start": window["start"], "end": window["end"],
                   "frames": window["frames"]},
        "required_parts": sorted(required),
        "built_parts": sorted(built),
        "measured": {k: measured.get(k) for k in
                     ("displacement", "translate_down", "screen_pixels", "rotation_degrees",
                      "scale_ratio_min", "scale_ratio_max", "height_ratio_min",
                      "distinct_positions", "parts_moved", "parts_removed",
                      "start_world", "end_world")},
        "requirement": requirement,
        "encoded_motion": stats,
        "centre_motion": hero_energy,
        "background_motion": background_energy,
        "failures": failures,
        "warnings": warnings,
        "passed": not failures,
    }


def verify_delivery(path, *, width, height, fps, min_seconds=20.0, max_seconds=70.0):
    info = probe(path)
    video = video_stream(info)
    audio = audio_stream(info)
    failures = []
    if not video:
        return {"passed": False, "failures": ["no video stream"]}
    if not audio:
        failures.append("no audio stream")
    if video.get("codec_name") != "h264":
        failures.append(f"video codec {video.get('codec_name')} is not h264")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (width, height):
        failures.append(f"resolution {video.get('width')}x{video.get('height')} "
                        f"!= {width}x{height}")
    rate = video.get("r_frame_rate") or video.get("avg_frame_rate")
    if rate not in {f"{fps}/1", f"{fps}.0/1.0"}:
        failures.append(f"frame rate {rate} != {fps}/1")
    duration = float(info.get("format", {}).get("duration", 0.0) or 0.0)
    if not (min_seconds <= duration <= max_seconds):
        failures.append(f"duration {duration:.2f}s outside {min_seconds}-{max_seconds}s")
    if audio:
        levels = audio_levels(path)
        if levels["mean_db"] is None or levels["mean_db"] < -40:
            failures.append(f"narration track is silent (mean {levels['mean_db']} dB)")
        if audio.get("channels") not in (1, 2):
            failures.append(f"unexpected audio channel count {audio.get('channels')}")
        audio_duration = float(audio.get("duration", 0) or 0)
        if abs(audio_duration - duration) > 1.0:
            failures.append(
                f"audio/video duration mismatch ({audio_duration:.2f}s vs {duration:.2f}s)")
    return {
        "passed": not failures,
        "failures": failures,
        "duration_seconds": round(duration, 3),
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": rate,
        "frames": video.get("nb_frames"),
        "audio_codec": (audio or {}).get("codec_name"),
        "audio_channels": (audio or {}).get("channels"),
        "audio_sample_rate": (audio or {}).get("sample_rate"),
    }


def check_scene_diversity(scene_reports, similarity_matrix, threshold=0.90):
    failures = []
    for a, row in similarity_matrix.items():
        for b, score in row.items():
            if int(b) <= int(a):
                continue
            if score >= threshold:
                failures.append(
                    f"scenes {a} and {b} are near-identical stills (SSIM {score:.3f})")
    subjects = [r["subject"] for r in scene_reports]
    actions = [r["action"] for r in scene_reports]
    templates = [r["template"] for r in scene_reports]
    if len(set(templates)) < max(3, len(scene_reports) - 2):
        failures.append(f"only {len(set(templates))} distinct templates across "
                        f"{len(scene_reports)} scenes")
    for label, values in (("subject", subjects), ("action", actions)):
        repeated = max(values.count(v) for v in set(values))
        if repeated > 2:
            failures.append(f"{label} {max(set(values), key=values.count)!r} repeats "
                            f"{repeated} times")
    return {
        "passed": not failures,
        "failures": failures,
        "distinct_templates": len(set(templates)),
        "subjects": subjects,
        "actions": actions,
        "max_pairwise_ssim": round(max((v for row in similarity_matrix.values()
                                        for v in row.values()), default=0.0), 3),
    }


def caption_alignment(cards_by_scene, windows, beats):
    """Captions must be derived from the spoken line and cover its window."""
    failures = []
    for cards, window, beat in zip(cards_by_scene, windows, beats):
        if not cards:
            failures.append(f"scene {window['index'] + 1} has no captions")
            continue
        spoken = set(beat["narration"].lower().split())
        caption_words = set(" ".join(" ".join(card["lines"]) for card in cards)
                            .lower().split())
        if not caption_words.issubset(spoken):
            failures.append(f"scene {window['index'] + 1} captions contain words that are "
                            f"not spoken in its beat")
        coverage = max(card["end"] for card in cards)
        if coverage < window["duration"] * 0.85:
            failures.append(
                f"scene {window['index'] + 1} captions stop at {coverage:.2f}s of "
                f"{window['duration']:.2f}s")
    return {"passed": not failures, "failures": failures}


def summarise(scene_reports):
    failed = [r for r in scene_reports if not r["passed"]]
    return {
        "passed": not failed,
        "scene_count": len(scene_reports),
        "failed_scenes": [r["scene_index"] for r in failed],
        "failures": [{"scene": r["scene_index"], "problems": r["failures"]} for r in failed],
    }


def distance(a, b):
    return math.dist(a, b)
