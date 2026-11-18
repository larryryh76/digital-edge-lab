"""Explicit render profiles for cheap CI previews and native-quality production.

The preview profile preserves the existing low-cost GitHub Actions path.
The production profile is intentionally GPU-only and must never silently fall
back to CPU or lower-quality output.
"""

from __future__ import annotations

import os


_PROFILES = {
    "preview": {
        "render_width": 288,
        "render_height": 512,
        "render_fps": 12,
        "output_width": 720,
        "output_height": 1280,
        "output_fps": 24,
        "engine": "BLENDER_EEVEE_NEXT",
        "samples": 1,
        "denoise": False,
        "require_gpu": False,
        "raytracing": False,
    },
    "production": {
        "render_width": 1080,
        "render_height": 1920,
        "render_fps": 24,
        "output_width": 1080,
        "output_height": 1920,
        "output_fps": 24,
        "engine": "CYCLES",
        "samples": 32,
        "denoise": True,
        "require_gpu": True,
        "raytracing": False,
    },
}


def get_render_profile(name: str | None = None) -> dict:
    """Return a copy of the selected profile; never silently downgrade unknown names."""
    selected = (name or os.getenv("DEL_RENDER_PROFILE", "preview")).strip().lower()
    if selected not in _PROFILES:
        allowed = ", ".join(sorted(_PROFILES))
        raise ValueError(f"Unknown DEL_RENDER_PROFILE {selected!r}; choose one of: {allowed}")
    return dict(_PROFILES[selected])


def profile_names() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))
