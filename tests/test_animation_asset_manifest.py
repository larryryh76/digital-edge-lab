import hashlib
import tempfile
import unittest
from pathlib import Path

from src.animation_asset_manifest import (
    AssetManifestError,
    parse_manifest,
    ready_assets,
    verify_ready_asset,
)


SOURCE = "https://example.org/asset"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"


def entry(status="candidate", **overrides):
    value = {
        "id": "test-asset",
        "title": "Test asset",
        "kind": "animation",
        "status": status,
        "source_url": SOURCE,
        "license_id": "CC0-1.0",
        "license_url": LICENSE,
        "compatible_rigs": ["test-rig"],
        "animation_clips": ["idle", "walk"],
        "attribution": "Test creator",
    }
    value.update(overrides)
    return value


class AnimationAssetManifestTests(unittest.TestCase):
    def test_candidate_is_not_ready_or_renderable(self):
        records = parse_manifest({"schema_version": 1, "assets": [entry()]})
        self.assertEqual(records[0].status, "candidate")
        self.assertEqual(ready_assets(records), [])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(AssetManifestError, "candidate is not renderable"):
                verify_ready_asset(records[0], Path(tmp))

    def test_ready_asset_requires_cc0_and_sha256_and_verifies_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"pinned test asset"
            (root / "anim.glb").write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            records = parse_manifest({"schema_version": 1, "assets": [
                entry(status="ready", file_format="glb", file_path="anim.glb", sha256=digest)
            ]})
            self.assertEqual(ready_assets(records), records)
            self.assertEqual(verify_ready_asset(records[0], root), root / "anim.glb")

    def test_ready_asset_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "asset.glb").write_bytes(b"tampered")
            records = parse_manifest({"schema_version": 1, "assets": [
                entry(status="ready", file_format="glb", file_path="asset.glb", sha256="0" * 64)
            ]})
            with self.assertRaisesRegex(AssetManifestError, "SHA-256 mismatch"):
                verify_ready_asset(records[0], root)

    def test_ready_asset_rejects_non_cc0_license(self):
        with self.assertRaisesRegex(AssetManifestError, "only verified CC0-1.0"):
            parse_manifest({"schema_version": 1, "assets": [
                entry(status="ready", license_id="CC-BY-4.0", file_format="glb",
                      file_path="asset.glb", sha256="1" * 64)
            ]})

    def test_candidate_cannot_claim_unverified_path_or_hash(self):
        with self.assertRaisesRegex(AssetManifestError, "candidate assets must not carry"):
            parse_manifest({"schema_version": 1, "assets": [entry(file_path="asset.glb")]})

    def test_path_traversal_is_rejected(self):
        with self.assertRaisesRegex(AssetManifestError, "safe relative path"):
            parse_manifest({"schema_version": 1, "assets": [
                entry(status="ready", file_format="glb", file_path="../asset.glb", sha256="1" * 64)
            ]})

    def test_duplicate_ids_and_unsupported_schema_fail(self):
        with self.assertRaisesRegex(AssetManifestError, "duplicate id"):
            parse_manifest({"schema_version": 1, "assets": [entry(), entry()]})
        with self.assertRaisesRegex(AssetManifestError, "unsupported manifest schema"):
            parse_manifest({"schema_version": 2, "assets": []})


if __name__ == "__main__":
    unittest.main()
