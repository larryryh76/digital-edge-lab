"""Narration synthesis with real audio-duration scene timing.

Timing is derived from measured audio, never from character counts: each
narrative beat is synthesised separately, measured with ffprobe, padded to its
own scene duration, and concatenated. The scene timeline therefore *is* the
audio timeline, so narration, captions and animation share one clock.

`ESPEAK_ONLY=1` (or running with --offline) uses a local deterministic
espeak-ng voice instead of the hosted TTS model. That path exists so the visual
engine and timing logic can be verified end-to-end without API access; it is
labelled as a fallback in the run report and is not a publication-quality voice.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

FPS = 24
SCENE_TAIL_SECONDS = 0.18
MIN_BEAT_SECONDS = 0.45

VOICE_DIRECTION = (
    "Voice direction for Edge, the Digital Edge Lab narrator: sound like a real, confident "
    "documentary storyteller speaking to one curious person. Warm, mid-low register, natural "
    "conversational rhythm, subtle curiosity, restrained emotion, clean consonants, short "
    "intentional pauses at commas and reveals. Emphasise only the key words. Do not sound "
    "robotic, overexcited, salesy, or like a news bulletin. Do not add words, ad-libs, or "
    "sound effects. Read the supplied line verbatim.\n\n"
)


class NarrationError(RuntimeError):
    pass


def probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise NarrationError(f"ffprobe rejected {path}: {result.stderr[-400:]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise NarrationError(f"unreadable duration for {path}") from exc


def mean_volume_db(path):
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        check=False, capture_output=True, text=True, timeout=60,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    return float(match.group(1)) if match else None


def gemini_tts(client, text, out_path, model):
    """Synthesise one beat with the hosted TTS model."""
    parts = client.generate(
        model,
        [{"text": VOICE_DIRECTION + text}],
        {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}},
        },
        deadline_seconds=140,
        attempts_per_model=2,
        label="tts",
    )
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            raw = base64.b64decode(inline["data"])
            mime = inline.get("mimeType") or inline.get("mime_type") or "audio/pcm;rate=24000"
            match = re.search(r"rate=(\d+)", mime)
            rate = int(match.group(1)) if match else 24000
            raw_path = Path(str(out_path) + ".pcm")
            raw_path.write_bytes(raw)
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1",
                 "-i", str(raw_path), str(out_path)],
                check=False, capture_output=True, text=True, timeout=90,
            )
            raw_path.unlink(missing_ok=True)
            if result.returncode:
                raise NarrationError(f"could not decode TTS audio: {result.stderr[-300:]}")
            return out_path
    raise NarrationError("TTS response contained no audio payload")


def find_local_voice():
    for binary in ("espeak-ng", "espeak"):
        path = shutil.which(binary)
        if path:
            return path
    return None


def local_tts(text, out_path, binary):
    result = subprocess.run(
        [binary, "-v", "en-us", "-s", "168", "-p", "44", "-g", "6", "-w", str(out_path), text],
        check=False, capture_output=True, text=True, timeout=90,
    )
    if result.returncode or not Path(out_path).exists():
        raise NarrationError(f"local voice failed: {result.stderr[-300:]}")
    return out_path


def pad_to(wav_in, wav_out, seconds):
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(wav_in), "-af",
         "aresample=48000,apad", "-t", f"{seconds:.4f}", "-ac", "1", "-ar", "48000",
         str(wav_out)],
        check=False, capture_output=True, text=True, timeout=90,
    )
    if result.returncode:
        raise NarrationError(f"could not pad {wav_in}: {result.stderr[-300:]}")


def synthesize(episode, work_dir, *, client=None, tts_model=None, offline=False):
    """Synthesise every beat, return (narration_wav, windows, report)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    local = find_local_voice()
    use_local = offline or client is None
    if use_local and not local:
        raise NarrationError(
            "Offline narration requested but neither espeak-ng nor espeak is installed; "
            "refusing to render a silent episode."
        )
    if not use_local and client is None:
        raise NarrationError("No TTS backend available")

    padded_files, windows, report_beats = [], [], []
    cursor = 0.0
    for i, beat in enumerate(episode["beats"]):
        raw = work_dir / f"beat_{i:02d}.wav"
        if use_local:
            local_tts(beat["narration"], raw, local)
            engine = "espeak-ng"
        else:
            gemini_tts(client, beat["narration"], raw, tts_model)
            engine = client.actual_models.get("tts") or tts_model
        spoken = probe_duration(raw)
        if spoken < MIN_BEAT_SECONDS:
            raise NarrationError(
                f"beat {i + 1} narration is only {spoken:.2f}s; refusing to ship a truncated line"
            )
        level = mean_volume_db(raw)
        if level is None or level < -45:
            raise NarrationError(f"beat {i + 1} narration is silent (mean {level} dB)")
        duration = max(1, round((spoken + SCENE_TAIL_SECONDS) * FPS)) / FPS
        padded = work_dir / f"beat_{i:02d}_padded.wav"
        pad_to(raw, padded, duration)
        padded_files.append(padded)
        windows.append({
            "index": i,
            "beat_id": beat["id"],
            "role": beat["role"],
            "start": round(cursor, 4),
            "end": round(cursor + duration, 4),
            "duration": round(duration, 4),
            "frames": int(round(duration * FPS)),
            "spoken_seconds": round(spoken, 4),
            "narration": beat["narration"],
        })
        report_beats.append({"index": i, "engine": engine, "spoken_seconds": round(spoken, 3),
                             "scene_seconds": round(duration, 3), "mean_db": level})
        cursor += duration

    concat_list = work_dir / "narration_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in padded_files) + "\n",
        encoding="utf-8",
    )
    narration = work_dir / "narration.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-ac", "1", "-ar", "48000", str(narration)],
        check=False, capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise NarrationError(f"could not concatenate narration: {result.stderr[-400:]}")
    total = probe_duration(narration)
    if abs(total - cursor) > 0.25:
        raise NarrationError(
            f"narration timeline drift: expected {cursor:.2f}s, measured {total:.2f}s"
        )
    report = {
        "engine": "espeak-ng-fallback" if use_local else "gemini-tts",
        "publication_quality_voice": not use_local,
        "model": tts_model,
        "total_seconds": round(total, 3),
        "beats": report_beats,
    }
    return narration, windows, report


def caption_cards(text, duration, max_chars=34):
    """Split a beat into sequential caption cards with derived timings."""
    words = text.strip().split()
    if not words:
        return []
    lines, current = [], []
    for word in words:
        candidate = " ".join(current + [word])
        if len(candidate) <= max_chars:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    groups, group = [], []
    for line in lines:
        if len(group) < 3 and len(" ".join(group + [line])) <= max_chars:
            group.append(line)
        else:
            if group:
                groups.append(group)
            group = [line]
    if group:
        groups.append(group)
    per_card = duration / max(1, len(groups))
    cards = []
    for i, group in enumerate(groups):
        cards.append({
            "lines": group,
            "start": round(i * per_card, 4),
            "end": round(min(duration, (i + 1) * per_card + 0.06), 4),
        })
    return cards


def timeline_summary(windows):
    return json.dumps([{k: w[k] for k in ("index", "start", "end", "frames")} for w in windows],
                      indent=2)
