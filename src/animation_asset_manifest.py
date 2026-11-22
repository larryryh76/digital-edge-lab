"""Manifest validation and integrity checks for curated animation/3D assets.

This module intentionally does not download assets or trust "free" claims. Assets
must be individually license-reviewed and pinned before being marked ready.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_KINDS = {"character", "animation", "environment", "prop", "material"}
SUPPORTED_FORMATS = {"blend", "glb", "gltf", "fbx", "hdr"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AssetManifestError(ValueError):
    """Raised when a manifest or asset violates the production trust policy."""


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    title: str
    kind: str
    status: str
    source_url: str
    license_id: str
    license_url: str
    file_format: str | None
    file_path: str | None
    sha256: str | None
    compatible_rigs: tuple[str, ...]
    animation_clips: tuple[str, ...]
    attribution: str | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssetManifestError(message)


def _safe_relative_path(value: Any, asset_id: str) -> str:
    _require(isinstance(value, str) and value.strip(), f"{asset_id}: ready asset needs file_path")
    path = Path(value)
    _require(not path.is_absolute() and ".." not in path.parts,
             f"{asset_id}: file_path must be a safe relative path")
    return path.as_posix()


def parse_manifest(data: Any) -> list[AssetRecord]:
    _require(isinstance(data, dict), "manifest must be a JSON object")
    _require(data.get("schema_version") == 1, "unsupported manifest schema_version")
    assets = data.get("assets")
    _require(isinstance(assets, list), "manifest assets must be a list")
    records: list[AssetRecord] = []
    seen: set[str] = set()
    for index, raw in enumerate(assets):
        _require(isinstance(raw, dict), f"assets[{index}] must be an object")
        asset_id = str(raw.get("id", "")).strip()
        _require(asset_id and asset_id not in seen, f"assets[{index}]: missing or duplicate id")
        seen.add(asset_id)
        status = raw.get("status")
        _require(status in {"candidate", "ready"}, f"{asset_id}: status must be candidate or ready")
        kind = raw.get("kind")
        _require(kind in SUPPORTED_KINDS, f"{asset_id}: unsupported kind {kind!r}")
        source_url = str(raw.get("source_url", "")).strip()
        license_id = str(raw.get("license_id", "")).strip()
        license_url = str(raw.get("license_url", "")).strip()
        _require(source_url.startswith("https://"), f"{asset_id}: source_url must be HTTPS")
        _require(license_id, f"{asset_id}: license_id is required")
        _require(license_url.startswith("https://"), f"{asset_id}: license_url must be HTTPS")
        file_format = raw.get("file_format")
        file_path = raw.get("file_path")
        digest = raw.get("sha256")
        if status == "ready":
            _require(license_id == "CC0-1.0",
                    f"{asset_id}: only verified CC0-1.0 assets may be production-ready")
            _require(file_format in SUPPORTED_FORMATS,
                    f"{asset_id}: unsupported or missing file_format")
            file_path = _safe_relative_path(file_path, asset_id)
            _require(isinstance(digest, str) and SHA256_RE.fullmatch(digest),
                    f"{asset_id}: ready assets require a valid SHA-256 pin")
        else:
            _require(file_path is None and digest is None,
                    f"{asset_id}: candidate assets must not carry unverified file/hash values")
        compatible_rigs = raw.get("compatible_rigs", [])
        animation_clips = raw.get("animation_clips", [])
        _require(isinstance(compatible_rigs, list), f"{asset_id}: compatible_rigs must be a list")
        _require(isinstance(animation_clips, list), f"{asset_id}: animation_clips must be a list")
        records.append(AssetRecord(
            asset_id=asset_id,
            title=str(raw.get("title", asset_id)).strip(),
            kind=kind,
            status=status,
            source_url=source_url,
            license_id=license_id,
            license_url=license_url,
            file_format=file_format,
            file_path=file_path,
            sha256=digest,
            compatible_rigs=tuple(str(x) for x in compatible_rigs),
            animation_clips=tuple(str(x) for x in animation_clips),
            attribution=str(raw.get("attribution", "")).strip() or None,
        ))
    return records


def load_manifest(path: Path) -> list[AssetRecord]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetManifestError(f"cannot read manifest {path}: {exc}") from exc
    return parse_manifest(data)


def verify_ready_asset(record: AssetRecord, asset_root: Path) -> Path:
    _require(record.status == "ready", f"{record.asset_id}: candidate is not renderable")
    _require(record.license_id == "CC0-1.0", f"{record.asset_id}: license is not production-approved")
    root = asset_root.resolve()
    path = (root / record.file_path).resolve()
    _require(root in path.parents,
             f"{record.asset_id}: resolved asset path escapes asset root")
    _require(path.is_file(), f"{record.asset_id}: asset file not found: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _require(digest == record.sha256, f"{record.asset_id}: SHA-256 mismatch")
    return path


def ready_assets(records: list[AssetRecord]) -> list[AssetRecord]:
    return [record for record in records if record.status == "ready"]
