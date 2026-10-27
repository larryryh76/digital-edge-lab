"""Render the CI run summary from the pipeline's own run report.

Usage:
    python src/run_summary.py [output/run-report.json]

Prints Markdown to stdout. The workflow appends it to $GITHUB_STEP_SUMMARY so a
green run always states what it delivered — including when the delivery is a
degraded (API-unavailable) build rather than a generated episode.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summary(report):
    narration = report.get("narration") or {}
    media = report.get("delivery_media") or {}
    lines = [
        "### Digital Edge Lab run",
        "",
        f"- status: **{report.get('status')}**",
        f"- origin: `{report.get('origin')}`",
        f"- voice: `{narration.get('engine')}` "
        f"(publication quality: {narration.get('publication_quality_voice')})",
        f"- duration: {media.get('duration_seconds')}s "
        f"{media.get('width')}x{media.get('height')} @ {media.get('fps')}",
        f"- scenes: {report.get('scene_count')}, "
        f"distinct templates: {(report.get('scene_diversity') or {}).get('distinct_templates')}",
        f"- failed gates: {report.get('failed_gates') or 'none'}",
    ]
    if report.get("degraded"):
        degraded = report["degraded"]
        lines.append(f"- **DEGRADED DELIVERY** ({degraded.get('stage')}): "
                     f"{str(degraded.get('reason', ''))[:300]}")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else ROOT / "output" / "run-report.json"
    if not path.is_file():
        print("No run report was produced - see the failure artifact.")
        return 0
    report = json.loads(path.read_text(encoding="utf-8"))
    print(summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
