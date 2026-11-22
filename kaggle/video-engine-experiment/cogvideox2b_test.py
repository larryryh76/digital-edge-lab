#!/usr/bin/env python3
"""One-shot real text-to-video test using CogVideoX-2B on a free Kaggle T4.

This is a quality experiment, not yet a production engine. It generates a single
6-second 49-frame clip, reframes it vertically, and preserves source + metadata
for visual QA before any integration is accepted.
"""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path

OUT = Path("/kaggle/working")
OUT.mkdir(parents=True, exist_ok=True)
PROMPT = (
    "Cinematic macro documentary shot, photorealistic: inside a dark server room, "
    "a tiny luminous data pulse travels through a transparent fiber-optic cable, "
    "the camera follows it smoothly in a continuous tracking shot, then pulls back "
    "to reveal rows of tall server racks with realistic blinking lights and subtle "
    "fan movement. Physical depth, natural lens motion, volumetric atmosphere, "
    "realistic reflections, coherent movement, no text, no logos, no jump cuts."
)
START = time.time()
def run(cmd):
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, timeout=600)

def main():
    import torch
    from diffusers import CogVideoXPipeline
    from diffusers.utils import export_to_video
    print("GPU:", torch.cuda.get_device_name(0), flush=True)
    print("VRAM total GiB:", round(torch.cuda.get_device_properties(0).total_memory/1024**3,2), flush=True)
    model = os.environ.get("DEL_T2V_MODEL", "zai-org/CogVideoX-2b")
    pipe = CogVideoXPipeline.from_pretrained(model, torch_dtype=torch.float16)
    # T4-friendly offload: keep weights on CPU except active modules.
    pipe.enable_sequential_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    generator = torch.Generator(device="cuda").manual_seed(4242)
    frames = pipe(
        prompt=PROMPT,
        num_videos_per_prompt=1,
        num_inference_steps=20,
        num_frames=49,
        guidance_scale=6,
        generator=generator,
    ).frames[0]
    raw = OUT / "cogvideox2b_raw.mp4"
    export_to_video(frames, str(raw), fps=8)
    # Reframe center-cropped landscape model output to 9:16 portrait, 720x1280.
    portrait = OUT / "cogvideox2b_portrait.mp4"
    run(["ffmpeg","-y","-v","error","-i",str(raw),"-vf",
         "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
         "-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p",
         "-an",str(portrait)])
    # QA stills at three different times to demonstrate actual clip variation.
    for sec in range(6):
        run(["ffmpeg","-y","-v","error","-ss",str(sec),"-i",str(portrait),
             "-frames:v","1",str(OUT/f"frame_{sec:02d}.jpg")])
    meta = {
        "model": model, "prompt": PROMPT, "seconds": 6.0, "frames": 49, "fps": 8,
        "inference_steps": 20, "seed": 4242, "gpu": torch.cuda.get_device_name(0),
        "elapsed_seconds": round(time.time()-START,2), "status": "experiment_only",
        "notes": "Must be manually inspected for coherent subject motion, frame stability, and composition before production integration."
    }
    (OUT/"experiment_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_name,width,height,avg_frame_rate",
         "-of","json",str(portrait)])
    print("Experiment output:", OUT, flush=True)
if __name__ == "__main__":
    main()
