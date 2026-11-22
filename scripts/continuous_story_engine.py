#!/usr/bin/env python3
"""Zero-budget continuous-story short engine.

This engine is deliberately separate from the legacy Blender fallback. It renders a
single continuous audio track and a sequence of moving, layered 2D cinematic shots:
a persistent protagonist, props, camera moves, action arcs, transitions, captions,
and an audio bed. It is a publishability experiment, not a claim of 3D realism.
"""
from __future__ import annotations
import json, math, os, shutil, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "continuous-story"
W, H, FPS = 540, 960, 24
DURATION = 42.0
SCENE_BOUNDS = (0.0, 7.0, 14.0, 22.0, 29.0, 35.0, 42.0)
BG = (6, 9, 20)
ACCENTS = [(49, 196, 255), (145, 95, 255), (255, 170, 74), (92, 240, 178), (255, 94, 145), (115, 160, 255)]

def fnt(size, bold=False):
    names = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for n in names:
        if Path(n).exists():
            return ImageFont.truetype(n, size)
    return ImageFont.load_default()

def lerp(a,b,p): return a + (b-a)*p
def scene_at(t):
    for i in range(len(SCENE_BOUNDS)-1):
        if t < SCENE_BOUNDS[i+1]:
            return i, (t-SCENE_BOUNDS[i])/(SCENE_BOUNDS[i+1]-SCENE_BOUNDS[i])
    return len(SCENE_BOUNDS)-2, 1.0

def glow(d, x, y, r, color, alpha=180):
    for k in range(4,0,-1):
        rr = int(r*(1+k*.7))
        d.ellipse((x-rr,y-rr,x+rr,y+rr), fill=(*color, max(8, alpha//(k+1))))
    d.ellipse((x-r,y-r,x+r,y+r), fill=(*color, alpha))

def draw_actor(d, x, y, scale, phase, accent):
    # Persistent protagonist with articulated limbs and a readable pose.
    head_r = int(24*scale)
    d.ellipse((x-head_r, y-150*scale-head_r, x+head_r, y-150*scale+head_r), fill=(235,239,250,255))
    d.rounded_rectangle((x-31*scale, y-125*scale, x+31*scale, y-45*scale), radius=int(16*scale), fill=(22,28,54,255), outline=(*accent,220), width=max(1,int(3*scale)))
    arm = math.sin(phase*math.tau)*22*scale
    d.line((x-22*scale, y-112*scale, x-70*scale, y-55*scale+arm), fill=(*accent,255), width=max(2,int(7*scale)))
    d.line((x+22*scale, y-112*scale, x+70*scale, y-55*scale-arm), fill=(*accent,255), width=max(2,int(7*scale)))
    d.line((x-12*scale, y-45*scale, x-32*scale, y+45*scale), fill=(220,225,240,255), width=max(2,int(8*scale)))
    d.line((x+12*scale, y-45*scale, x+32*scale, y+45*scale), fill=(220,225,240,255), width=max(2,int(8*scale)))

def frame(t, captions):
    scene, p = scene_at(t)
    accent = ACCENTS[scene % len(ACCENTS)]
    im = Image.new("RGB", (W,H), BG)
    d = ImageDraw.Draw(im, "RGBA")
    # Camera drift and depth layers.
    camx = math.sin(t*0.37) * 22
    camy = math.sin(t*0.21) * 10
    for layer in range(9):
        yy = int(150 + layer*92 + camy + math.sin(t*(0.4+layer*.03))*8)
        d.line((0, yy, W, yy), fill=(*accent, 20+layer*2), width=1)
    for i in range(26):
        x = int((i*91 + t*(13+scene*3)) % (W+80) - 40)
        y = int((i*53 + math.sin(t*.8+i)*34) % H)
        r = 1 + i%3
        d.ellipse((x-r,y-r,x+r,y+r), fill=(*accent, 55+(i%4)*25))
    # Scene-specific action.
    cx = int(W*.5 + camx)
    actor_y = int(590 + math.sin(t*1.4)*5)
    draw_actor(d, cx, actor_y, 1.15, t/3.0 + scene*.25, accent)
    if scene == 0:
        orb_x = int(150 + p*210); orb_y = int(355 - 50*math.sin(p*math.pi))
        glow(d, orb_x, orb_y, 18+int(8*math.sin(t*3)), accent)
        d.line((cx-70, actor_y-100, orb_x, orb_y), fill=(*accent,100), width=3)
    elif scene == 1:
        for i in range(4):
            x = int(145 + i*82 + math.sin(t+i)*10)
            y = int(300 + i*22 + math.cos(t*.9+i)*16)
            d.rounded_rectangle((x,y,x+62,y+30), radius=8, fill=(18,25,49,240), outline=(*accent,190), width=2)
            d.line((x+12,y+15,x+47,y+15), fill=(*accent,180), width=3)
    elif scene == 2:
        for i in range(8):
            a = t*.9+i*math.tau/8
            x = int(cx + math.cos(a)*(110+22*math.sin(t+i)))
            y = int(350 + math.sin(a)*90)
            d.line((cx,410,x,y), fill=(*accent,90), width=2)
            glow(d,x,y,7,ACCENTS[(i+1)%len(ACCENTS)],120)
    elif scene == 3:
        left = int(120 + 34*math.sin(t)); right = int(420 + 34*math.cos(t*.7))
        d.line((left,390,right,390), fill=(*accent,140), width=5)
        glow(d,left,390,11,ACCENTS[1],170); glow(d,right,390,11,ACCENTS[3],170)
    elif scene == 4:
        ring = int(70 + 22*math.sin(t*2))
        d.arc((cx-ring,390-ring,cx+ring,390+ring), int(t*120), int(t*120+270), fill=(*accent,220), width=7)
        d.arc((cx-ring-26,390-ring-26,cx+ring+26,390+ring+26), int(-t*90), int(-t*90+220), fill=(*ACCENTS[2],180), width=5)
    else:
        for i in range(5):
            x = int(cx + math.cos(t*.7+i)*150)
            y = int(360 + math.sin(t*.8+i*1.4)*130)
            d.line((cx,410,x,y), fill=(*ACCENTS[i],100), width=2)
            glow(d,x,y,9,ACCENTS[i],170)
    # Kinetic title and captions remain tied to the same continuous clock.
    d.rounded_rectangle((22,42,W-22,96), radius=18, fill=(3,6,16,210), outline=(*accent,150), width=2)
    d.text((38,58), "DIGITAL EDGE LAB", font=fnt(18,True), fill=(230,238,255,255))
    d.text((W-125,60), f"{scene+1:02d}/06", font=fnt(16,True), fill=(*accent,255))
    d.text((35,150), ["THE SIGNAL ARRIVES","SELECTIVE MEMORY","SORT THE NOISE","CONNECT CONTEXT","UPDATE THE LOOP","RECALL WITH PURPOSE"][scene], font=fnt(21,True), fill=(*accent,255))
    d.rounded_rectangle((24,780,W-24,910), radius=22, fill=(2,5,14,225), outline=(*accent,120), width=2)
    words = captions[scene].split()
    line = ""; lines=[]
    for w in words:
        test=(line+" "+w).strip()
        if d.textbbox((0,0),test,font=fnt(18,True))[2] <= W-74: line=test
        else: lines.append(line); line=w
    if line: lines.append(line)
    yy=808
    for line in lines[:4]:
        d.text((38,yy), line, font=fnt(18,True), fill=(248,250,255,255)); yy += 28
    prog=t/DURATION
    d.rounded_rectangle((28,H-42,W-28,H-31), radius=5, fill=(255,255,255,35))
    d.rounded_rectangle((28,H-42,28+int((W-56)*prog),H-31), radius=5, fill=(*accent,255))
    return im

def synth_voice(text, out, voice_bin):
    subprocess.run([voice_bin, "-v", "en-us+f3", "-s", "166", "-p", "40", "-a", "165", "-w", str(out), text], check=True, timeout=120)

def main():
    voice_bin = shutil.which("espeak-ng") or shutil.which("espeak")
    if not voice_bin:
        print("ERROR: espeak-ng/espeak missing", file=sys.stderr); return 2
    narration = [
        "What if the next answer got better because the system remembered less?",
        "A useful memory does not keep every sentence. It keeps the decision, the goal, and the detail that changes what comes next.",
        "Then it sorts the noise, links related facts, and pulls back only the context that belongs in this moment.",
        "But memory cannot stay frozen. Old assumptions need to be corrected, and stale details need to disappear.",
        "That turns a chat history into a working loop: store, retrieve, check, update.",
        "The result is simple. Better answers do not come from remembering everything. They come from recalling the right thing at the right time."
    ]
    captions = [
        "Better answers can start with remembering less.",
        "Keep decisions, goals, and details that change the next step.",
        "Sort the noise. Link the facts. Retrieve only what belongs here.",
        "Correct old assumptions. Remove stale details.",
        "Store. Retrieve. Check. Update.",
        "Useful AI depends on timing, not total recall."
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "work"; work.mkdir(parents=True, exist_ok=True)
    voice = work / "narration.wav"
    synth_voice(" ".join(narration), voice, voice_bin)
    mp4 = OUT / "continuous-story.mp4"
    cmd = ["ffmpeg","-y","-loglevel","warning","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-",
           "-i",str(voice),"-f","lavfi","-i",f"anoisesrc=color=pink:sample_rate=44100:duration={DURATION}",
           "-filter_complex","[1:a]aresample=44100,apad,atrim=0:42,volume=1.0[voice];[2:a]lowpass=f=170,volume=0.018,afade=t=in:st=0:d=2,afade=t=out:st=38:d=4[bed];[voice][bed]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
           "-map","0:v:0","-map","[a]","-t",str(DURATION),"-c:v","libx264","-preset","ultrafast","-crf","22","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for n in range(int(DURATION*FPS)):
            p.stdin.write(frame(n/FPS, captions).tobytes())
        p.stdin.close(); code=p.wait(timeout=300)
    except Exception:
        p.kill(); raise
    if code != 0 or not mp4.exists():
        return 1
    probe = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(mp4)],capture_output=True,text=True,check=True)
    data=json.loads(probe.stdout)
    streams=data.get("streams",[]); dur=float(data.get("format",{}).get("duration",0))
    v=next((s for s in streams if s.get("codec_type")=="video"),{})
    ok=dur>=40 and v.get("width")==W and v.get("height")==H and any(s.get("codec_type")=="audio" for s in streams)
    report={"status":"pass" if ok else "fail","engine":"continuous-story-v1","audio_track":"single continuous narration + ambience","duration_seconds":round(dur,2),"resolution":f"{W}x{H}","fps":FPS,"mp4":str(mp4)}
    (OUT/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
