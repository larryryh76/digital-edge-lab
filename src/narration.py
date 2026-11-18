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
import os
import re
import shutil
import subprocess
from pathlib import Path

FPS = 24
SCENE_TAIL_SECONDS = 0.18
# Preserve pitch while gently correcting only local lines that are measurably rushed.
TARGET_LOCAL_WPM = 158
LOCAL_WPM_FAST_THRESHOLD = 168
MIN_BEAT_SECONDS = 0.45
# A narrator physically cannot deliver a line slower than this. Any hosted TTS
# response outside the band means the model spoke something other than the line
# (run #84: a 15-word line came back as 40s of audio because the long style
# paragraph was read aloud), so it is rejected instead of becoming a scene.
MIN_SECONDS_PER_WORD = 0.15
MAX_SECONDS_PER_WORD = 1.15

# Kept to a single clause: the longer the style text, the more likely a speech
# model performs it as narration instead of treating it as direction.
STYLE_BRIEF = "Male narrator; warm low-mid pitch, varied intonation, expressive cadence, relaxed pace, natural pauses. Read only:"


def plausibility(text, seconds):
    """Return (plausible, seconds_per_word) for one spoken line."""
    words = max(1, len(text.split()))
    rate = seconds / words
    return MIN_SECONDS_PER_WORD <= rate <= MAX_SECONDS_PER_WORD, rate


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


def _tts_request(client, prompt, out_path, model):
    """One hosted TTS request; writes a wav and returns it."""
    parts = client.generate(
        model,
        [{"text": prompt}],
        {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}},
        },
        deadline_seconds=120,
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


def gemini_tts(client, text, out_path, model, *, log=None):
    """Synthesise one beat, verifying the audio really is that one line.

    The styled prompt is tried first; if the result cannot plausibly be this
    line, the bare line is retried before the scene is allowed to use it. A
    response that is wrong twice fails the episode with the measured rates.
    """
    attempts = []
    for prompt, mode in ((f"{STYLE_BRIEF} {text}", "styled"), (text, "bare")):
        _tts_request(client, prompt, out_path, model)
        seconds = probe_duration(out_path)
        ok, rate = plausibility(text, seconds)
        attempts.append({"mode": mode, "seconds": round(seconds, 3),
                         "seconds_per_word": round(rate, 3), "accepted": ok})
        if ok:
            if log:
                log({"stage": "tts_verified", **attempts[-1]})
            return out_path
        Path(out_path).unlink(missing_ok=True)
    raise NarrationError(
        "hosted TTS returned audio that cannot be this line "
        f"({len(text.split())} words): {json.dumps(attempts)}"
    )


_KOKORO_ENGINE = None
_KOKORO_ENGINE_KEY = None


def find_local_voice():
    """Prefer the commercially licensed Kokoro neural voice; eSpeak is diagnostic-only."""
    model = Path(os.environ.get("KOKORO_MODEL", ""))
    voices = Path(os.environ.get("KOKORO_VOICES", ""))
    if model.is_file() and voices.is_file():
        try:
            import kokoro_onnx  # noqa: F401
            return "kokoro"
        except ImportError:
            pass
    for binary in ("espeak-ng", "espeak"):
        path = shutil.which(binary)
        if path:
            return path
    return None


def local_tts(text, out_path, binary):
    if binary == "kokoro":
        model = Path(os.environ.get("KOKORO_MODEL", ""))
        voices = Path(os.environ.get("KOKORO_VOICES", ""))
        if not model.is_file() or not voices.is_file():
            raise NarrationError("Kokoro selected but KOKORO_MODEL or KOKORO_VOICES is missing")
        try:
            global _KOKORO_ENGINE, _KOKORO_ENGINE_KEY
            key = (str(model.resolve()), str(voices.resolve()))
            if _KOKORO_ENGINE is None or _KOKORO_ENGINE_KEY != key:
                from kokoro_onnx import Kokoro

                _KOKORO_ENGINE = Kokoro(str(model), str(voices))
                _KOKORO_ENGINE_KEY = key
            audio, sample_rate = _KOKORO_ENGINE.create(
                text,
                voice=os.environ.get("KOKORO_VOICE", "am_michael"),
                speed=float(os.environ.get("KOKORO_SPEED", "1.0")),
                lang="en-us",
            )
            import soundfile as sf

            sf.write(str(out_path), audio, sample_rate, subtype="PCM_16")
        except Exception as exc:
            raise NarrationError(f"Kokoro neural voice failed: {type(exc).__name__}: {exc}") from exc
        if not Path(out_path).is_file() or Path(out_path).stat().st_size < 1024:
            raise NarrationError("Kokoro produced an empty or invalid audio file")
        return out_path

    # eSpeak is a deterministic diagnostic fallback, not a publication voice.
    result = subprocess.run(
        [binary, "-v", "en-us", "-s", "148", "-p", "43", "-g", "5",
         "-a", "165", "-w", str(out_path), text],
        check=False, capture_output=True, text=True, timeout=45,
    )
    if result.returncode or not Path(out_path).exists():
        raise NarrationError(f"local voice failed: {result.stderr[-300:]}")
    return out_path


def normalize_local_pace(path, text, *, target_wpm=TARGET_LOCAL_WPM):
    """Gently slow overly brisk local narration without changing its pitch.

    Returns measured before/after WPM. Hosted TTS is never time-stretched here.
    """
    words = max(1, len(text.split()))
    before_seconds = probe_duration(path)
    before_wpm = 60.0 * words / max(before_seconds, 0.01)
    if before_wpm <= LOCAL_WPM_FAST_THRESHOLD:
        return {"before_wpm": round(before_wpm, 1), "after_wpm": round(before_wpm, 1),
                "stretched": False}
    factor = max(0.78, min(0.96, target_wpm / before_wpm))
    temp_path = Path(str(path) + ".paced.wav")
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-filter:a",
         f"atempo={factor:.4f}", "-ar", "48000", "-ac", "1", str(temp_path)],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if result.returncode or not temp_path.exists():
        temp_path.unlink(missing_ok=True)
        raise NarrationError(f"local narration pace correction failed: {result.stderr[-300:]}")
    temp_path.replace(path)
    after_seconds = probe_duration(path)
    after_wpm = 60.0 * words / max(after_seconds, 0.01)
    if after_wpm > LOCAL_WPM_FAST_THRESHOLD:
        raise NarrationError(
            f"local voice remains too fast after pitch-preserving correction "
            f"({after_wpm:.1f} WPM); rejecting this narration rather than shipping rushed speech"
        )
    return {"before_wpm": round(before_wpm, 1), "after_wpm": round(after_wpm, 1),
            "stretched": True, "atempo": round(factor, 4)}


def pause_after_role(role):
    """A short silence that gives hooks, reveals and payoffs room to land."""
    return {"hook": 0.38, "reveal": 0.48, "payoff": 0.42, "ending": 0.42}.get(role, 0.20)


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
        pace_report = None
        if use_local:
            local_tts(beat["narration"], raw, local)
            pace_report = normalize_local_pace(raw, beat["narration"])
            engine = "kokoro-neural" if local == "kokoro" else "espeak-ng-fallback"
        else:
            gemini_tts(client, beat["narration"], raw, tts_model)
            engine = client.actual_models.get("tts") or tts_model
        spoken = probe_duration(raw)
        if spoken < MIN_BEAT_SECONDS:
            raise NarrationError(
                f"beat {i + 1} narration is only {spoken:.2f}s; refusing to ship a truncated line"
            )
        ok, rate = plausibility(beat["narration"], spoken)
        if not ok:
            raise NarrationError(
                f"beat {i + 1} narration is {spoken:.2f}s for "
                f"{len(beat['narration'].split())} words ({rate:.2f}s/word); the voice "
                "did not read this beat's line"
            )
        level = mean_volume_db(raw)
        if level is None or level < -45:
            raise NarrationError(f"beat {i + 1} narration is silent (mean {level} dB)")
        role_pause = pause_after_role(beat.get("role", ""))
        duration = max(1, round((spoken + SCENE_TAIL_SECONDS + role_pause) * FPS)) / FPS
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
                             "scene_seconds": round(duration, 3), "role_pause_seconds": role_pause,
                             "pace": pace_report, "mean_db": level})
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
        "engine": ("kokoro-neural" if local == "kokoro" else "espeak-ng-fallback") if use_local else "gemini-tts",
        "publication_quality_voice": (not use_local) or local == "kokoro",
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
