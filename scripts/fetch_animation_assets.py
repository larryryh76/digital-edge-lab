#!/usr/bin/env python3
"""Fetch and verify free Quaternius CC0 animation libraries for Blender tests.

No paid API is used. The itch.io file endpoint returns a temporary signed URL.
Archives are verified before ZIP parsing and only the expected GLB is extracted.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PACKS = {
    "ual1": {
        "id": "quaternius-ual1-standard",
        "upload_id": 17958403,
        "source_url": "https://quaternius.com/packs/universalanimationlibrary.html",
        "license_id": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "archive_sha256": "cc73fc4e495b82958207316596317a3f40b9fa38065bde1027937452da537724",
        "archive_name": "UAL1_Standard.zip",
        "glb_path": "Unreal-Godot/UAL1_Standard.glb",
        "glb_name": "UAL1_Standard.glb",
        "glb_sha256": "69591853d817488edaa8fd9bf8fc1d821eaeaf789f8627b3cd23b41c4ed67997",
    },
    "ual2": {
        "id": "quaternius-ual2-standard",
        "upload_id": 17958478,
        "source_url": "https://quaternius.com/packs/universalanimationlibrary2.html",
        "license_id": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "archive_sha256": "4008ea208a604773a2b2177d965f0f5d3195498b5bf838c3f5785d68e95f2a68",
        "archive_name": "UAL2_Standard.zip",
        "glb_path": "Unreal-Godot/UAL2_Standard.glb",
        "glb_name": "UAL2_Standard.glb",
        "glb_sha256": None,
    },
}


class AssetFetchError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _response_bytes(urlopen, request_or_url, timeout: int) -> bytes:
    with urlopen(request_or_url, timeout=timeout) as response:
        return response.read()


def resolve_download_url(pack: dict, urlopen=urllib.request.urlopen) -> str:
    endpoint = (
        f"https://quaternius.itch.io/universal-animation-library"
        f"/file/{pack['upload_id']}?source=game_download&as_props=1"
    )
    if pack["upload_id"] == 17958478:
        endpoint = (
            f"https://quaternius.itch.io/universal-animation-library-2"
            f"/file/{pack['upload_id']}?source=game_download&as_props=1"
        )
    request = urllib.request.Request(
        endpoint,
        data=b"",
        headers={"User-Agent": "DigitalEdgeLab-CC0AssetVerifier/1.0"},
        method="POST",
    )
    last_error = None
    # itch.io occasionally rate-limits its signed-download resolver (HTTP 429).
    # Retry boundedly with exponential backoff before failing this proof.
    import time
    for attempt in range(4):
        try:
            payload = json.loads(_response_bytes(urlopen, request, 40).decode("utf-8"))
            break
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt == 3:
                raise AssetFetchError(f"itch.io download-url resolution failed after 4 attempts: {exc}") from exc
            time.sleep(2 ** (attempt + 1)
    signed_url = payload.get("url")
    if not isinstance(signed_url, str) or not signed_url.startswith("https://"):
        raise AssetFetchError("itch.io returned no HTTPS download URL")
    return signed_url


def _fetch_archive(pack: dict, archive_path: Path, urlopen) -> None:
    signed_url = resolve_download_url(pack, urlopen=urlopen)
    try:
        payload = _response_bytes(urlopen, signed_url, 120)
    except OSError as exc:
        raise AssetFetchError(f"asset archive download failed: {exc}") from exc
    actual = sha256_bytes(payload)
    if actual != pack["archive_sha256"]:
        raise AssetFetchError(
            f"{pack['id']}: archive SHA-256 mismatch (got {actual})"
        )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temp = archive_path.with_suffix(archive_path.suffix + ".tmp")
    temp.write_bytes(payload)
    temp.replace(archive_path)


def _read_verified_archive(pack: dict, archive_path: Path, urlopen) -> bytes:
    if archive_path.exists():
        payload = archive_path.read_bytes()
        if sha256_bytes(payload) == pack["archive_sha256"]:
            return payload
        archive_path.unlink()
    _fetch_archive(pack, archive_path, urlopen)
    return archive_path.read_bytes()


def _extract_expected_glb(pack: dict, archive_bytes: bytes, destination: Path) -> str:
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(archive_bytes)) as archive:
            entries = [
                info for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).name == pack["glb_name"]
            ]
            if len(entries) != 1:
                candidates = [info.filename for info in entries]
                raise AssetFetchError(
                    f"{pack['id']}: expected exactly one {pack['glb_name']} by basename; "
                    f"found {len(entries)} candidates: {candidates}"
                )
            info = entries[0]
            glb = archive.read(info)
    except (zipfile.BadZipFile, OSError) as exc:
        raise AssetFetchError(f"{pack['id']}: verified archive is not a readable ZIP: {exc}") from exc
    if glb[:4] != b"glTF" or len(glb) < 12:
        raise AssetFetchError(f"{pack['id']}: extracted asset is not a valid GLB header")
    declared_length = int.from_bytes(glb[8:12], "little")
    if declared_length != len(glb):
        raise AssetFetchError(f"{pack['id']}: GLB declared length does not match file size")
    digest = sha256_bytes(glb)
    expected_glb = pack.get("glb_sha256")
    if expected_glb and digest != expected_glb:
        raise AssetFetchError(f"{pack['id']}: extracted GLB SHA-256 mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(glb)
    temporary.replace(destination)
    return digest


def fetch_pack(pack_key: str, asset_dir: Path, cache_dir: Path, urlopen=urllib.request.urlopen) -> Path:
    if pack_key not in PACKS:
        raise AssetFetchError(f"unknown pack {pack_key!r}; choose from {sorted(PACKS)}")
    pack = PACKS[pack_key]
    archive_path = cache_dir / pack["archive_name"]
    archive_bytes = _read_verified_archive(pack, archive_path, urlopen)
    asset_path = asset_dir / pack["glb_name"]
    digest = _extract_expected_glb(pack, archive_bytes, asset_path)
    metadata = {
        "asset_id": pack["id"],
        "asset_path": asset_path.name,
        "asset_sha256": digest,
        "archive_sha256": pack["archive_sha256"],
        "source_url": pack["source_url"],
        "license_id": pack["license_id"],
        "license_url": pack["license_url"],
    }
    (asset_dir / f"{asset_path.stem}.provenance.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return asset_path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", choices=("ual1", "ual2", "both"), default="ual1")
    parser.add_argument("--asset-dir", type=Path, default=Path("assets/animations"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/animation-packs"))
    args = parser.parse_args()
    selected = ("ual1", "ual2") if args.pack == "both" else (args.pack,)
    try:
        for key in selected:
            path = fetch_pack(key, args.asset_dir, args.cache_dir)
            print(f"Verified {key}: {path}")
    except AssetFetchError as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
