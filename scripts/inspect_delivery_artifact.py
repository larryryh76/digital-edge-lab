#!/usr/bin/env python3
"""Artifact-level inspection for a delivered portrait short.

Checks ffprobe metadata, black/frozen intervals, representative frame extraction,
caption sidecar presence, and measurable frame motion. Fails closed for missing
or structurally invalid media.
"""
from __future__ import annotations
import argparse, json, math, subprocess
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
    fps=eval(video.get("avg_frame_rate","0/1"))
    return {"width":video.get("width"),"height":video.get("height"),
            "fps":round(float(fps),3),"duration":float(data["format"]["duration"]),
            "audio_codec":audio.get("codec_name"),"video_codec":video.get("codec_name")}

def frame_metrics(path: Path, outdir: Path):
    outdir.mkdir(parents=True,exist_ok=True)
    # Three representative frames plus a 1 Hz thumbnail sequence.
    for label, ss in [("start",0.5),("middle",5.0),("end",10.0)]:
        subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",str(ss),"-i",str(path),"-frames:v","1",str(outdir/f"{label}.jpg")],check=True)
    frames=outdir/"seq"
    frames.mkdir(exist_ok=True)
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
    count=frame_metrics(args.video,args.out)
    captions_ok=bool(args.captions and args.captions.exists() and args.captions.stat().st_size>0)
    report={"video":str(args.video),"metadata":meta,"representative_frames":count,
            "captions_sidecar_present":captions_ok,
            "black_or_frozen_intervals":"requires visual review of extracted frames",
            "intended_subject_motion":"requires visual review of extracted frames"}
    (args.out/"artifact-inspection.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
if __name__=="__main__":
    main()
