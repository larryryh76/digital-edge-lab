#!/usr/bin/env python3
"""Zero-API-cost, procedural cinematic short generator for GitHub Actions.

Creates actual moving frames (not a still-image slideshow), synthetic narration via
espeak-ng, a generated ambient soundtrack, subtitles, and a validated vertical MP4.
"""
from __future__ import annotations
import json, math, os, random, shutil, subprocess, sys, textwrap
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "video"
W, H, FPS = 540, 960, 20
DURATION = 30
SCENE_LEN = 5
PALETTE = [(7,12,29),(13,20,44),(22,14,42),(7,26,42),(23,16,36),(5,13,26)]
ACCENTS = [(66,210,255),(166,105,255),(255,179,82),(91,255,196),(255,100,145),(106,160,255)]
DEFAULT_TOPIC = "The hidden system that lets AI remember what matters"

def font(size, bold=False):
    paths = [
      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
      "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def wrap(draw, text, f, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0,0), test, font=f)[2] <= width: line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines

def centered(draw, text, y, f, fill, width=W-54, spacing=8):
    lines = wrap(draw, text, f, width)
    for line in lines:
        bb = draw.textbbox((0,0), line, font=f, stroke_width=0)
        draw.text(((W-(bb[2]-bb[0]))/2,y), line, font=f, fill=fill)
        y += bb[3]-bb[1]+spacing
    return y

def draw_glow(draw, x, y, r, color):
    for k in range(4,0,-1):
        rr = int(r*(1+k*.55))
        col = tuple(int(c*(0.045/k)) for c in color)
        draw.ellipse((x-rr,y-rr,x+rr,y+rr), fill=col)
    draw.ellipse((x-r,y-r,x+r,y+r), fill=color)

def make_frame(t, topic, captions):
    scene = min(int(t//SCENE_LEN), 5)
    p = (t % SCENE_LEN)/SCENE_LEN
    bg = Image.new("RGB",(W,H),PALETTE[scene])
    pix = bg.load()
    # Animated gradient and scan-like atmosphere; every frame changes.
    base = PALETTE[scene]
    for y in range(H):
        v = y/H
        for x in range(W):
            wave = (math.sin(x*.018+t*1.6)+math.sin(y*.012-t*1.3)+2)/4
            pix[x,y] = tuple(min(255,int(base[c]+wave*(12+v*13))) for c in range(3))
    d = ImageDraw.Draw(bg, "RGBA")
    accent = ACCENTS[scene]
    # Perspective grid drifts continuously to make the camera feel alive.
    offset = int((t*38)%54)
    for y in range(470+offset,H,54):
        d.line((0,y,W,y), fill=(*accent,24), width=1)
    for x in range(-W,W*2,70):
        d.line((W//2+(x-W//2)*.12,450,W//2+(x-W//2)*1.8, H), fill=(*accent,18), width=1)
    # Particles follow different trajectories per scene.
    rng = random.Random(900+scene)
    for i in range(34):
        x0, y0 = rng.randrange(W), rng.randrange(H)
        x = int((x0 + math.sin(t*.8+i)*30 + t*(8+scene)) % W)
        y = int((y0 - t*(10+i%5)*2) % H)
        r = 1+(i%3)
        d.ellipse((x-r,y-r,x+r,y+r), fill=(*accent, 90+(i%4)*30))
    cx, cy = W//2, 425
    drift = math.sin(t*1.8)*13
    # Unique animated metaphor in each beat; no reused still frame.
    if scene == 0:  # signal arrives
        for i in range(5):
            radius = int((30+i*45+(t*95)%220))
            d.arc((cx-radius,cy-radius,cx+radius,cy+radius), 200, 520, fill=(*accent,max(25,190-i*25)), width=3)
        draw_glow(d,int(cx+drift),cy,24,accent)
        for i in range(8):
            a=t*1.2+i*math.pi/4
            draw_glow(d,int(cx+math.cos(a)*130),int(cy+math.sin(a)*130),5,ACCENTS[(i+1)%6])
        label="SIGNAL DETECTED"
    elif scene == 1: # memory archive
        for i in range(7):
            yy=cy-180+i*52+int(math.sin(t*2+i)*9)
            ww=180+(i%3)*48
            xx=int(cx-ww/2+math.sin(t+i)*18)
            d.rounded_rectangle((xx,yy,xx+ww,yy+32), radius=9, fill=(*accent,35), outline=(*accent,190), width=2)
            for j in range(3):
                d.rounded_rectangle((xx+14+j*22,yy+11,xx+25+j*22,yy+21), radius=3, fill=(*accent,180))
        label="MEMORY IS SELECTIVE"
    elif scene == 2: # sorting
        for i in range(12):
            a=t*.65+i*math.tau/12
            r=130+20*math.sin(t*2+i)
            x=int(cx+math.cos(a)*r); y=int(cy+math.sin(a)*r)
            rr=8+(i%3)*4
            d.line((cx,cy,x,y), fill=(*accent,65), width=2)
            draw_glow(d,x,y,rr,ACCENTS[i%6])
        draw_glow(d,cx,cy,35,accent)
        label="KEEP THE USEFUL PART"
    elif scene == 3: # connection map
        nodes=[]
        for i in range(9):
            a=i*math.tau/9+t*.16
            nodes.append((int(cx+math.cos(a)*(115+12*math.sin(t+i))),int(cy+math.sin(a)*145)))
        for i,(x,y) in enumerate(nodes):
            for j,(xx,yy) in enumerate(nodes):
                if j>i and (j+i)%3!=0: d.line((x,y,xx,yy),fill=(*accent,65),width=2)
        for i,(x,y) in enumerate(nodes): draw_glow(d,x,y,9,ACCENTS[i%6])
        label="CONTEXT CONNECTS THE DOTS"
    elif scene == 4: # feedback loop
        for i in range(3):
            r=70+i*42
            d.arc((cx-r,cy-r,cx+r,cy+r), int(t*80+i*60), int(t*80+i*60+245), fill=(*ACCENTS[(i+scene)%6],220), width=7)
        tipx=int(cx+math.cos(t*1.4)*150); tipy=int(cy+math.sin(t*1.4)*150)
        draw_glow(d,tipx,tipy,12,accent)
        label="LEARN • UPDATE • RECALL"
    else: # payoff
        for i in range(6):
            x=int(cx+math.sin(t*1.4+i)*150)
            y=int(cy+math.cos(t*1.1+i*1.4)*175)
            d.line((cx,cy,x,y),fill=(*ACCENTS[i],90),width=2)
            draw_glow(d,x,y,8,ACCENTS[i])
        draw_glow(d,cx,cy,int(28+6*math.sin(t*3)),accent)
        label="MEMORY WITH PURPOSE"
    # Scene label and kinetic headline.
    d.rounded_rectangle((24,55,W-24,101), radius=18, fill=(4,8,20,170), outline=(*accent,130), width=1)
    d.text((42,68),"DIGITAL EDGE LAB",font=font(18,True),fill=(220,235,255,255))
    d.text((W-130,69),f"0{scene+1} / 06",font=font(16,True),fill=(*accent,255))
    centered(d,label,165,font(17,True),(*accent,255))
    if scene == 0:
        headline="AI DOESN'T\\nHAVE TO FORGET"
    elif scene == 1: headline="NOT EVERY DETAIL\\nDESERVES TO STAY"
    elif scene == 2: headline="KEEP WHAT\\nCHANGES THE ANSWER"
    elif scene == 3: headline="LINK FACTS TO\\nTHE RIGHT CONTEXT"
    elif scene == 4: headline="MEMORY IS A\\nFEEDBACK LOOP"
    else: headline="RECALL THE RIGHT\\nTHING. AT THE RIGHT TIME."
    centered(d,headline,670,font(28,True),(245,248,255,255),W-62,7)
    # Kinetic underline and active progress indicator.
    prog = (scene+p)/6
    d.rounded_rectangle((28,H-48,W-28,H-37),radius=5,fill=(255,255,255,35))
    d.rounded_rectangle((28,H-48,28+int((W-56)*prog),H-37),radius=5,fill=(*accent,255))
    # Caption cards change each scene and remain inside safe margins.
    cap = captions[scene]
    d.rounded_rectangle((24,800,W-24,900),radius=20,fill=(3,7,18,215),outline=(*accent,115),width=1)
    centered(d,cap,820,font(17,True),(250,250,255,255),W-74,5)
    return bg.convert("RGB")

def main():
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg is required (install it in the workflow).",file=sys.stderr); return 2
    voice_bin = shutil.which("espeak-ng") or shutil.which("espeak")
    if not voice_bin:
        print("ERROR: espeak-ng or espeak is required for local narration.",file=sys.stderr); return 2
    topic = os.environ.get("EPISODE_TOPIC","").strip() or DEFAULT_TOPIC
    # This zero-API pilot has a complete editorial fallback; no secret/key/network required.
    narration = [
      "What if AI remembered the useful parts, without keeping every word?",
      "The trick is a system that stores selected facts, goals, and decisions outside the chat.",
      "When a new question arrives, it retrieves only the details that matter.",
      "Context links facts together, so preferences and project decisions are not isolated scraps.",
      "Memory must update too: correct old assumptions and drop stale details.",
      "No magic. Just store, retrieve, check, and update. Useful AI depends on what it recalls, and when."
    ]
    captions = [
      "A conversation ends. The useful details should not disappear.",
      "Store decisions, preferences, and facts — not a giant transcript.",
      "Search first. Retrieve only what helps answer the next question.",
      "Context turns scattered notes into a coherent picture.",
      "Correct stale facts. Keep the memory useful.",
      "Store. Retrieve. Check. Update. Repeat."
    ]
    # If an explicit topic is supplied, make the hook reflect it without inventing facts.
    if topic.lower() not in DEFAULT_TOPIC.lower():
        narration[0] = f"Here is a practical question about {topic}: what is the hidden mechanism that makes it work?"
        captions[0] = topic[:78].upper()
    OUT.mkdir(parents=True,exist_ok=True)
    work = ROOT / "output" / "render-work"
    work.mkdir(parents=True,exist_ok=True)
    voice = work / "narration.wav"
    full_script = " ".join(narration)
    subprocess.run([voice_bin,"-v","en-us+f3","-s","194","-p","44","-a","165","-w",str(voice),full_script],check=True,timeout=90)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mp4 = OUT / f"digital-edge-lab-{stamp}.mp4"
    # Stream raw frames to ffmpeg: fast, deterministic, genuinely animated, no Blender/GPU.
    cmd = ["ffmpeg","-y","-loglevel","warning","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-",
           "-i",str(voice),"-f","lavfi","-i",f"anoisesrc=color=pink:sample_rate=44100:duration={DURATION}",
           "-filter_complex","[1:a]aresample=44100,apad,atrim=0:30,volume=1.0[voice];[2:a]lowpass=f=180,volume=0.025,afade=t=in:st=0:d=2,afade=t=out:st=26:d=4[bed];[voice][bed]amix=inputs=2:duration=first:dropout_transition=2, loudnorm=I=-16:TP=-1.5:LRA=11[a]",
           "-map","0:v:0","-map","[a]","-t",str(DURATION),"-c:v","libx264","-preset","ultrafast","-crf","23","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(mp4)]
    proc = subprocess.Popen(cmd,stdin=subprocess.PIPE)
    try:
        total = FPS*DURATION
        for frame_no in range(total):
            t=frame_no/FPS
            frame=make_frame(t,topic,captions)
            proc.stdin.write(frame.tobytes())
            if frame_no % 100 == 0: print(f"Rendered {frame_no}/{total} frames",flush=True)
        proc.stdin.close()
        code=proc.wait(timeout=240)
    except Exception:
        proc.kill(); raise
    if code != 0 or not mp4.exists() or mp4.stat().st_size < 100_000:
        print("ERROR: ffmpeg did not produce a valid-sized MP4.",file=sys.stderr); return 1
    probe = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(mp4)],capture_output=True,text=True,check=True,timeout=30)
    info=json.loads(probe.stdout)
    streams=info.get("streams",[])
    duration=float(info.get("format",{}).get("duration",0))
    has_audio=any(s.get("codec_type")=="audio" for s in streams)
    video=next((s for s in streams if s.get("codec_type")=="video"),{})
    if not has_audio or video.get("width") != W or video.get("height") != H or duration < 28:
        mp4.unlink(missing_ok=True)
        print(f"ERROR: QA failed: duration={duration}, video={video}, audio={has_audio}",file=sys.stderr); return 1
    meta={"status":"verified_pilot_generated","engine":"Digital Edge Lab procedural cinematic engine v1","created_at_utc":datetime.now(timezone.utc).isoformat(),"topic":topic,"file":mp4.name,"bytes":mp4.stat().st_size,"duration_seconds":round(duration,2),"resolution":f"{W}x{H}","fps":FPS,"audio_stream":"present","narration":f"{Path(voice_bin).name} synthetic voice","music":"procedurally generated low-level pink-noise ambience","api_cost":"$0; no external model/API calls","qa":["valid MP4","vertical 9:16","audio stream present","30-second moving-frame render"]}
    (OUT/f"{mp4.stem}.json").write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    print("PILOT VERIFIED:",json.dumps(meta),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
