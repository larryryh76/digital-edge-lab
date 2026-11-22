#!/usr/bin/env python3
"""Real text-to-video pilot using Wan 2.1 T2V 1.3B on a free Kaggle T4.

This remains an isolated quality experiment until actual video and frames are
reviewed. The model produces native portrait clips (480x832) rather than a
landscape video center-cropped into a Shorts frame.
"""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path

OUT=Path("/kaggle/working")
OUT.mkdir(parents=True,exist_ok=True)
PROMPT=(
 "Cinematic photorealistic technology documentary, native vertical composition. "
 "Macro close-up of a tiny bright blue data pulse racing through a glass fiber-optic cable; "
 "the camera tracks alongside the moving pulse, then smoothly pulls back to reveal a towering "
 "dark server room with rows of rack lights, realistic reflections, subtle fan motion and "
 "volumetric haze. The pulse travels visibly through the cable. Physical depth, natural motion, "
 "stable subject, high contrast lighting, no words, no captions, no logos, no montage cuts."
)
START=time.time()
def run(cmd):
 print("$"," ".join(map(str,cmd)),flush=True)
 subprocess.run(cmd,check=True,timeout=900)

def main():
 run([__import__("sys").executable,"-m","pip","install","--disable-pip-version-check",
      "diffusers==0.35.1","transformers==4.51.3","accelerate==1.2.1","ftfy","imageio","imageio-ffmpeg"])
 import torch
 from diffusers import WanPipeline
 from diffusers.utils import export_to_video
 if not torch.cuda.is_available(): raise RuntimeError("No Kaggle GPU detected")
 gpu=torch.cuda.get_device_name(0)
 print("GPU:",gpu,"VRAM GiB:",round(torch.cuda.get_device_properties(0).total_memory/1024**3,2),flush=True)
 model=os.environ.get("DEL_WAN_MODEL","Wan-AI/Wan2.1-T2V-1.3B-Diffusers")
 pipe=WanPipeline.from_pretrained(model,torch_dtype=torch.float16)
 pipe.enable_model_cpu_offload()
 result=pipe(prompt=PROMPT,num_frames=81,height=832,width=480,guidance_scale=5.0,num_inference_steps=20)
 frames=result.frames[0]
 raw=OUT/"wan21_raw.mp4"
 export_to_video(frames,str(raw),fps=16)
 portrait=OUT/"wan21_portrait.mp4"
 run(["ffmpeg","-y","-v","error","-i",str(raw),"-vf",
      "scale=720:1280:flags=lanczos","-c:v","libx264","-preset","fast","-crf","19",
      "-pix_fmt","yuv420p","-an",str(portrait)])
 from PIL import Image,ImageChops,ImageStat
 for sec in range(6):
  run(["ffmpeg","-y","-v","error","-ss",str(sec),"-i",str(portrait),
       "-frames:v","1",str(OUT/f"frame_{sec:02d}.jpg")])
 motion=[]
 for sec in range(1,6):
  a=Image.open(OUT/f"frame_{sec-1:02d}.jpg").convert("RGB")
  b=Image.open(OUT/f"frame_{sec:02d}.jpg").convert("RGB")
  diff=ImageChops.difference(a,b)
  mean_delta=sum(ImageStat.Stat(diff).mean)/3
  changed=sum(1 for v in diff.convert("L").getdata() if v>8)/(a.width*a.height)
  motion.append({"interval":f"{sec-1}-{sec}s","mean_abs_rgb_delta":round(mean_delta,3),"changed_pixel_fraction":round(changed,4)})
 frozen=[m for m in motion if m["mean_abs_rgb_delta"]<1.0 or m["changed_pixel_fraction"]<0.01]
 qa={"intervals":motion,"frozen_intervals":frozen,"pass":not frozen,
     "limitation":"Pixel-difference QA detects near-freeze only; it does not prove coherent subject motion."}
 (OUT/"motion_qa.json").write_text(json.dumps(qa,indent=2))
 print("MOTION_QA:",json.dumps(qa),flush=True)
 if frozen: raise RuntimeError(f"Motion QA rejected generated video: {frozen}")
 meta={"model":model,"prompt":PROMPT,"resolution":"480x832 native portrait","seconds":5.0,
       "frames":81,"fps":16,"inference_steps":20,"gpu":gpu,
       "elapsed_seconds":round(time.time()-START,2),"status":"experiment_only",
       "qa":qa,"notes":"Manual visual inspection of the full clip is required before any production integration."}
 (OUT/"experiment_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
 run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_name,width,height,avg_frame_rate",
      "-of","json",str(portrait)])
 print("Video engine experiment outputs:",OUT,flush=True)
if __name__=="__main__": main()
