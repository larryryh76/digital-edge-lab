"""Kaggle GPU worker for native-quality Digital Edge Lab rendering.

This file is uploaded as a private Kaggle script kernel by the optional
GitHub Actions workflow. The workflow replaces SOURCE_SHA before upload.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCE_SHA = "__SOURCE_SHA__"
REPOSITORY = "https://github.com/larryryh76/digital-edge-lab.git"
BLENDER_URL = "https://download.blender.org/release/Blender4.2/blender-4.2.11-linux-x64.tar.xz"
PIPER_MODEL_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/ryan/medium/en_US-ryan-medium.onnx"
)
PIPER_CONFIG_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/ryan/medium/en_US-ryan-medium.onnx.json"
)
ROOT = Path("/kaggle/working")
REPO = ROOT / "digital-edge-lab"
DELIVERY = REPO / "output" / "delivery"


def run(argv, *, cwd=None, env=None, timeout=None):
    print("$ " + " ".join(str(part) for part in argv), flush=True)
    subprocess.run(argv, cwd=cwd, env=env, check=True, timeout=timeout)


def download(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DigitalEdgeLab/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)
    if destination.stat().st_size < 1024:
        raise RuntimeError(f"Downloaded file is unexpectedly small: {destination}")


def install_system_dependencies():
    run(["apt-get", "update"])
    run([
        "apt-get", "install", "-y", "--no-install-recommends",
        "ffmpeg", "espeak-ng", "libegl1", "libegl-mesa0", "libgl1",
        "libglx-mesa0", "libgl1-mesa-dri", "libxkbcommon0", "libxi6",
        "libxxf86vm1", "libxfixes3", "libxrender1", "libsm6", "libice6",
        "libxext6", "libgomp1", "libxrandr2", "libxinerama1",
    ])


def install_blender() -> Path:
    blender_dir = ROOT / "blender-4.2.11"
    blender_bin = blender_dir / "blender"
    if blender_bin.exists():
        return blender_bin
    archive = ROOT / "blender-4.2.11-linux-x64.tar.xz"
    download(BLENDER_URL, archive)
    blender_dir.mkdir(parents=True, exist_ok=True)
    run(["tar", "-xJf", str(archive), "-C", str(blender_dir),
         "--strip-components=1"])
    archive.unlink(missing_ok=True)
    if not blender_bin.exists():
        raise RuntimeError("Pinned Blender binary was not installed")
    return blender_bin


def install_python_dependencies():
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "-r", str(REPO / "requirements.txt")])
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "piper-tts"])
    voice_dir = ROOT / "piper-voice"
    download(PIPER_MODEL_URL, voice_dir / "en_US-ryan-medium.onnx")
    download(PIPER_CONFIG_URL, voice_dir / "en_US-ryan-medium.onnx.json")
    return voice_dir / "en_US-ryan-medium.onnx"


def prepare_hdri():
    """Use a CC0 Poly Haven studio HDRI when the public API is reachable."""
    sys.path.insert(0, str(REPO / "src"))
    try:
        from polyhaven_assets import download_hdri

        path, manifest_path, manifest = download_hdri(
            ROOT / "polyhaven-assets", slug="studio_small_03", resolution="1k"
        )
        print(f"Poly Haven HDRI ready: {manifest['source_url']} ({manifest['resolution']})",
              flush=True)
        return path, manifest_path, manifest
    except Exception as exc:
        # This asset is an enhancement, not a hard dependency. Keep the procedural
        # studio lighting if Poly Haven is temporarily unavailable.
        print(f"Poly Haven HDRI unavailable; using built-in studio world: {exc}", flush=True)
        return None, None, None


def checkout_exact_source():
    if SOURCE_SHA == "__SOURCE_SHA__" or len(SOURCE_SHA) != 40:
        raise RuntimeError("GitHub workflow did not pin the source commit SHA")
    if REPO.exists():
        shutil.rmtree(REPO)
    run(["git", "clone", "--depth", "1", "--branch", "main", REPOSITORY, str(REPO)])
    run(["git", "fetch", "--depth", "1", "origin", SOURCE_SHA], cwd=REPO)
    run(["git", "checkout", "--detach", SOURCE_SHA], cwd=REPO)
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    if actual != SOURCE_SHA:
        raise RuntimeError(f"Source pin mismatch: expected {SOURCE_SHA}, got {actual}")


def verify_delivery():
    report_path = DELIVERY / "run-report.json"
    video_path = DELIVERY / "digital-edge-lab-pilot.mp4"
    if not report_path.is_file() or not video_path.is_file():
        raise RuntimeError("Pipeline did not produce both the MP4 and run-report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") not in {"verified_delivery", "verified_degraded_delivery"}:
        raise RuntimeError(f"Delivery status is not verified: {report.get('status')}")
    if report.get("failed_gates"):
        raise RuntimeError(f"Delivery report contains failed gates: {report['failed_gates']}")
    media = report.get("delivery_media", {})
    if (media.get("width"), media.get("height")) != (1080, 1920):
        raise RuntimeError(f"Expected native 1080x1920 output, got {media}")
    fps = str(media.get("fps", ""))
    if fps not in {"24/1", "24"}:
        raise RuntimeError(f"Expected 24fps output, got {fps}")

    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate",
        "-of", "json", str(video_path),
    ], text=True)
    stream = json.loads(probe)["streams"][0]
    if (stream.get("width"), stream.get("height")) != (1080, 1920):
        raise RuntimeError(f"Encoded MP4 dimensions do not match 1080x1920: {stream}")
    if stream.get("avg_frame_rate") != "24/1":
        raise RuntimeError(f"Encoded MP4 frame rate is not 24fps: {stream}")
    return report, video_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if not Path("/kaggle").exists():
        raise RuntimeError("This worker must run inside a Kaggle Notebook environment")
    print("GPU inventory:", flush=True)
    run(["nvidia-smi", "-L"])
    checkout_exact_source()
    install_system_dependencies()
    blender_bin = install_blender()
    piper_model = install_python_dependencies()
    hdri_path, hdri_manifest_path, hdri_manifest = prepare_hdri()

    env = os.environ.copy()
    env.update({
        "PATH": str(blender_bin.parent) + os.pathsep + env.get("PATH", ""),
        "PIPER_MODEL": str(piper_model),
        "DEL_RENDER_PROFILE": "production",
        "DEL_RENDER_WORKERS": "1",
        "DEL_RENDER_SECONDS_PER_FRAME": "5.0",
        "DEL_RENDER_STARTUP_SECONDS": "180",
        "DEL_RENDER_PHASE_BUDGET_SECONDS": "7200",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    })
    if hdri_path:
        env["DEL_POLYHAVEN_HDRI"] = str(hdri_path)
        env["DEL_POLYHAVEN_STRENGTH"] = "0.28"
    print(f"Rendering exact source commit {SOURCE_SHA} with native 1080p GPU profile", flush=True)
    run([
        sys.executable, "src/pipeline.py", "--offline",
        "--plan", "plans/quantization-on-device.json",
    ], cwd=REPO, env=env, timeout=7800)

    report, video_path = verify_delivery()
    if hdri_manifest:
        report["external_assets"] = [hdri_manifest]
        (DELIVERY / "ASSET_ATTRIBUTION.txt").write_text(
            "HDRI: Studio Small 03 by Greg Zaal via Poly Haven (CC0). "
            "Powered by Poly Haven.\n"
            + hdri_manifest["source_url"] + "\n",
            encoding="utf-8",
        )
        (DELIVERY / "video-description.txt").write_text(
            "3D environment HDRI: Studio Small 03 by Greg Zaal via Poly Haven (CC0). "
            "Powered by Poly Haven.\n" + hdri_manifest["source_url"] + "\n",
            encoding="utf-8",
        )
        (DELIVERY / "run-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    output_zip = ROOT / "digital-edge-lab-delivery.zip"
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in DELIVERY.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(DELIVERY))
    shutil.copy2(video_path, ROOT / video_path.name)
    shutil.copy2(DELIVERY / "run-report.json", ROOT / "run-report.json")
    metadata = {
        "source_sha": SOURCE_SHA,
        "render_profile": "production",
        "resolution": "1080x1920",
        "fps": 24,
        "status": report.get("status"),
        "failed_gates": report.get("failed_gates", []),
        "gpu": subprocess.check_output(["nvidia-smi", "-L"], text=True).strip(),
        "blender": subprocess.check_output([str(blender_bin), "--version"], text=True).splitlines()[0],
        "video_sha256": sha256_file(video_path),
    }
    (ROOT / "production-render-metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
