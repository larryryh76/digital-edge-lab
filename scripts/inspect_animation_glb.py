#!/usr/bin/env python3
"""Validate real glTF 2.0 binary asset structure and humanoid animation content."""
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path


class GLBInspectionError(ValueError):
    pass


JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def inspect_glb(path: Path, min_animations: int = 20, min_joints: int = 40) -> dict:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"glTF":
        raise GLBInspectionError(f"{path.name}: invalid GLB header")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length != len(data):
        raise GLBInspectionError(f"{path.name}: unsupported version or length mismatch")
    offset = 12
    document = None
    chunks = []
    while offset + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if length < 0 or offset + length > len(data):
            raise GLBInspectionError(f"{path.name}: invalid chunk length")
        chunk = data[offset:offset + length]
        offset += length
        chunks.append(chunk_type)
        if chunk_type == JSON_CHUNK:
            if document is not None:
                raise GLBInspectionError(f"{path.name}: multiple JSON chunks")
            try:
                document = json.loads(chunk.decode("utf-8").rstrip(" \t\r\n\0"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GLBInspectionError(f"{path.name}: invalid glTF JSON: {exc}") from exc
    if offset != len(data) or document is None or chunks[0] != JSON_CHUNK:
        raise GLBInspectionError(f"{path.name}: missing JSON chunk or trailing data")
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    skins = document.get("skins", [])
    animations = document.get("animations", [])
    if not meshes:
        raise GLBInspectionError(f"{path.name}: no skinned meshes found")
    if not skins:
        raise GLBInspectionError(f"{path.name}: no armature skin found")
    joint_count = max((len(skin.get("joints", [])) for skin in skins), default=0)
    if joint_count < min_joints:
        raise GLBInspectionError(f"{path.name}: humanoid rig has only {joint_count} joints")
    if len(animations) < min_animations:
        raise GLBInspectionError(
            f"{path.name}: only {len(animations)} animations; expected at least {min_animations}"
        )
    accessors = document.get("accessors", [])
    animation_names = []
    total_channels = 0
    total_duration = 0.0
    for index, animation in enumerate(animations):
        name = animation.get("name")
        channels = animation.get("channels", [])
        samplers = animation.get("samplers", [])
        if not isinstance(name, str) or not name.strip():
            raise GLBInspectionError(f"{path.name}: animation {index} is unnamed")
        if not channels:
            raise GLBInspectionError(f"{path.name}: animation {name} has no channels")
        duration = 0.0
        for channel in channels:
            target = channel.get("target", {})
            node = target.get("node")
            if not isinstance(node, int) or not 0 <= node < len(nodes):
                raise GLBInspectionError(f"{path.name}: animation {name} targets an invalid node")
            sampler_index = channel.get("sampler")
            if not isinstance(sampler_index, int) or not 0 <= sampler_index < len(samplers):
                raise GLBInspectionError(f"{path.name}: animation {name} references an invalid sampler")
            accessor_index = samplers[sampler_index].get("input")
            if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
                raise GLBInspectionError(f"{path.name}: animation {name} has an invalid time accessor")
            accessor = accessors[accessor_index]
            bounds = accessor.get("max", [])
            minimum = accessor.get("min", [])
            if not bounds or not minimum:
                raise GLBInspectionError(f"{path.name}: animation {name} has no time bounds")
            end_time = float(bounds[0])
            start_time = float(minimum[0])
            if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
                raise GLBInspectionError(f"{path.name}: animation {name} has invalid duration")
            duration = max(duration, end_time - start_time)
        animation_names.append(name)
        total_channels += len(channels)
        total_duration += duration
    return {
        "file": path.name,
        "bytes": len(data),
        "nodes": len(nodes),
        "meshes": len(meshes),
        "skins": len(skins),
        "joint_count": joint_count,
        "animation_count": len(animations),
        "channel_count": total_channels,
        "sum_clip_seconds": round(total_duration, 3),
        "animation_names": animation_names,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--min-animations", type=int, default=20)
    parser.add_argument("--min-joints", type=int, default=40)
    args = parser.parse_args()
    reports = []
    for file in args.files:
        reports.append(inspect_glb(file, args.min_animations, args.min_joints))
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
