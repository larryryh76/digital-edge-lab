"""Fetch and verify curated CC0 HDRIs from the Poly Haven public API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

API_BASE = "https://api.polyhaven.com/v2/files"
ASSET_BASE = "https://polyhaven.com/a"
USER_AGENT = "DigitalEdgeLab/1.0 (https://github.com/larryryh76/digital-edge-lab)"


def select_hdri_file(payload: dict, preferred_resolution: str = "1k") -> dict:
    """Select a small EXR/HDR file from a released Poly Haven v2 file response."""
    data = payload.get("data", payload)
    hdri = data.get("hdri", {})
    resolutions = [preferred_resolution, "1k", "2k", "4k", "8k"]
    seen = set()
    for resolution in resolutions:
        if resolution in seen:
            continue
        seen.add(resolution)
        formats = hdri.get(resolution, {})
        for file_format in ("exr", "hdr"):
            entry = formats.get(file_format)
            if entry and entry.get("url"):
                return {
                    "url": entry["url"],
                    "md5": entry.get("md5"),
                    "resolution": resolution,
                    "format": file_format,
                }
    raise ValueError("Poly Haven API response contains no downloadable HDRI file")


def download_hdri(destination_dir, slug="studio_small_03", resolution="1k"):
    """Download one curated HDRI, verify its checksum, and write attribution metadata."""
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(f"{API_BASE}/{slug}", headers=headers, timeout=30)
    response.raise_for_status()
    asset = select_hdri_file(response.json(), resolution)
    destination = destination_dir / f"{slug}_{asset['resolution']}.{asset['format']}"
    if not destination.is_file():
        with requests.get(asset["url"], headers=headers, stream=True, timeout=(30, 180)) as download:
            download.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in download.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    if destination.stat().st_size < 1024:
        destination.unlink(missing_ok=True)
        raise ValueError("Poly Haven HDRI download is unexpectedly small")
    if asset.get("md5"):
        digest = hashlib.md5()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != asset["md5"].lower():
            destination.unlink(missing_ok=True)
            raise ValueError("Poly Haven HDRI checksum mismatch")
    manifest = {
        "provider": "Poly Haven",
        "asset_slug": slug,
        "asset_name": "Studio Small 03",
        "asset_type": "HDRI",
        "license": "CC0",
        "author": "Greg Zaal",
        "resolution": asset["resolution"],
        "format": asset["format"],
        "source_url": f"{ASSET_BASE}/{slug}",
        "download_url": asset["url"],
        "api_attribution": "Powered by Poly Haven",
        "file": destination.name,
    }
    manifest_path = destination_dir / f"{slug}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return destination, manifest_path, manifest
