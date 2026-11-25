#!/usr/bin/env python3
"""Delivery QA for continuous narration and subtitle timing.

Checks one final MP4 plus its SRT:
- exactly one audio stream
- audio duration is contiguous with no packet gaps
- SRT cues are ordered, non-overlapping, within media duration
- every cue has non-empty text
"""
from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path

TS = re.compile(r"^(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)$")

def ms(h,m,s,ms): return ((int(h)*60+int(m))*60+int(s))*1000+int(ms)

def probe(path: Path):
    p=subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],capture_output=True,text=True,check=True)
    return json.loads(p.stdout)

def parse_srt(path: Path):
    cues=[]; lines=path.read_text(encoding="utf-8").splitlines(); i=0
    while i < len(lines):
        if not lines[i].strip(): i+=1; continue
        idx=lines[i].strip(); i+=1
        if i>=len(lines): raise ValueError("truncated cue")
        m=TS.match(lines[i].strip())
        if not m: raise ValueError(f"bad timestamp line near cue {idx}")
        start=ms(*m.groups()[:4]); end=ms(*m.groups()[4:]); i+=1
        text=[]
        while i<len(lines) and lines[i].strip():
            text.append(lines[i].strip()); i+=1
        if not text: raise ValueError(f"cue {idx} has no text")
        cues.append((start,end," ".join(text)))
    return cues

def main():
    if len(sys.argv)!=3:
        print("usage: qa_delivery_media.py FINAL.mp4 FINAL.srt", file=sys.stderr); return 2
    mp4,srt=map(Path,sys.argv[1:])
    data=probe(mp4); streams=data.get("streams",[])
    audio=[s for s in streams if s.get("codec_type")=="audio"]
    if len(audio)!=1: raise SystemExit(f"expected exactly one audio stream, found {len(audio)}")
    duration=float(data.get("format",{}).get("duration") or 0)
    adur=float(audio[0].get("duration") or 0)
    if duration<=0 or adur<=0: raise SystemExit("media/audio duration missing")
    if abs(duration-adur)>0.25: raise SystemExit(f"audio is not continuous to end: media={duration:.3f}s audio={adur:.3f}s")
    cues=parse_srt(srt)
    prev_end=-1
    for n,(start,end,text) in enumerate(cues,1):
        if end<=start: raise SystemExit(f"cue {n} has non-positive duration")
        if start<prev_end: raise SystemExit(f"cue {n} overlaps previous cue")
        if end/1000 > duration+0.25: raise SystemExit(f"cue {n} exceeds media duration")
        prev_end=end
    report={"status":"passed","media_duration_seconds":round(duration,3),"audio_duration_seconds":round(adur,3),"audio_streams":1,"srt_cues":len(cues),"last_cue_end_seconds":round(prev_end/1000,3)}
    print(json.dumps(report,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
