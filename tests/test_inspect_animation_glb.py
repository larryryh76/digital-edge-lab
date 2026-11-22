import json
import struct
import tempfile
import unittest
from pathlib import Path

from scripts.inspect_animation_glb import GLBInspectionError, inspect_glb


def make_glb(document):
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((4 - len(raw) % 4) % 4)
    chunk = struct.pack("<II", len(raw), 0x4E4F534A) + raw
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


def valid_document(animations=1):
    nodes = [{"name": "Rig"}, {"name": "Bone"}]
    clips = [
        {"name": f"clip_{i}", "samplers": [{"input": 0}], "channels": [{"sampler": 0, "target": {"node": 1, "path": "translation"}}]}
        for i in range(animations)
    ]
    return {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "meshes": [{}],
        "skins": [{"joints": [0, 1]}],
        "accessors": [{"min": [0.0], "max": [1.0]}],
        "animations": clips,
    }


class GLBAnimationInspectionTests(unittest.TestCase):
    def test_valid_rig_and_animation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.glb"
            path.write_bytes(make_glb(valid_document(3)))
            report = inspect_glb(path, min_animations=3, min_joints=2)
            self.assertEqual(report["animation_count"], 3)
            self.assertEqual(report["joint_count"], 2)
            self.assertEqual(report["channel_count"], 3)
            self.assertEqual(report["animation_names"], ["clip_0", "clip_1", "clip_2"])

    def test_too_few_clips_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.glb"
            path.write_bytes(make_glb(valid_document(1)))
            with self.assertRaisesRegex(GLBInspectionError, "only 1 animations"):
                inspect_glb(path, min_animations=2, min_joints=2)

    def test_invalid_animation_target_fails(self):
        document = valid_document(1)
        document["animations"][0]["channels"][0]["target"]["node"] = 99
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.glb"
            path.write_bytes(make_glb(document))
            with self.assertRaisesRegex(GLBInspectionError, "invalid node"):
                inspect_glb(path, min_animations=1, min_joints=2)

    def test_invalid_header_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.glb"
            path.write_bytes(b"not-glb")
            with self.assertRaisesRegex(GLBInspectionError, "invalid GLB header"):
                inspect_glb(path)


if __name__ == "__main__":
    unittest.main()
