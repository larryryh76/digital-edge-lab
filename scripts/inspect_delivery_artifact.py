#!/usr/bin/env python3
"""Artifact-level inspection for a delivered portrait short."""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

def run(cmd):
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout

def probe(path: Path):
    data=json.loads(run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)]))
    streams=data.get("streams",[])
    video=next((s for s in streams if s.get("codec_type")=="video"),None)
    audio=next((s for s in streams if s.get("codec_type")=="audio"),None)
    if not video: raise SystemExit("missing video stream")
    if not audio: raise SystemExit("missing audio stream")
    num, den = (int(x) for x in video.get("avg_frame_rate","0/1").split("/",1))
    fps = num / den if den else 0.0
    return {
        "width": video.get("width"), "height": video.get("height"),
        "fps": round(fps,3), "duration": float(data["format"]["duration"]),
        "audio_codec": audio.get("codec_name"), "video_codec": video.get("codec_name"),
        "audio_sample_rate": int(audio.get("sample_rate","0") or 0),
    }

def detect_media_issues(path: Path):
    black = subprocess.run(
        ["ffmpeg","-hide_banner","-i",str(path),"-vf","blackdetect=d=0.8:pic_th=0.98","-an","-f","null","-"],
        text=True,capture_output=True
    )
    freeze = subprocess.run(
        ["ffmpeg","-hide_banner","-i",str(path),"-vf","freezedetect=n=0.003:d=1.2","-an","-f","null","-"],
        text=True,capture_output=True
    )
    return {
        "blackdetect": [line.strip() for line in (black.stderr or "").splitlines() if "black_start" in line],
        "freezedetect": [line.strip() for line in (freeze.stderr or "").splitlines() if "freeze_start" in line],
    }

def frame_metrics(path: Path, outdir: Path):
    outdir.mkdir(parents=True,exist_ok=True)
    meta=probe(path)
    duration=meta["duration"]
    points={"start":min(0.5,max(0.0,duration*0.05)),
            "middle":duration*0.5,
            "end":max(0.0,duration-0.5)}
    for label, ss in points.items():
        subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{ss:.3f}","-i",str(path),"-frames:v","1",str(outdir/f"{label}.jpg")],check=True)
    frames=outdir/"seq"; frames.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",str(path),"-vf","fps=1",str(frames/"%03d.jpg")],check=True)
    return len(list(frames.glob("*.jpg")))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("video",type=Path)
    ap.add_argument("--captions",type=Path)
    ap.add_argument("--out",type=Path,default=Path("artifact-inspection"))
    args=ap.parse_args()
    meta=probe(args.video)
    if meta["height"] <= meta["width"]: raise SystemExit("video is not portrait")
    if meta["duration"] < 20 or meta["duration"] > 90: raise SystemExit("duration outside short-form bounds")
    if meta["fps"] < 23 or meta["fps"] > 61: raise SystemExit("fps outside accepted range")
    if meta["audio_sample_rate"] < 16000: raise SystemExit("audio sample rate too low")
    count=frame_metrics(args.video,args.out)
    issues=detect_media_issues(args.video)
    captions_ok=bool(args.captions and args.captions.exists() and args.captions.stat().st_size>0)
    report={"video":str(args.video),"metadata":meta,"representative_frames":count,
            "captions_sidecar_present":captions_ok,
            "black_intervals":issues["blackdetect"],"frozen_intervals":issues["freezedetect"],
            "black_or_frozen_clear":not issues["blackdetect"] and not issues["freezedetect"],
            "intended_subject_motion":"requires visual review of extracted frames"}
    (args.out/"artifact-inspection.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
if __name__=="__main__":
    main()
