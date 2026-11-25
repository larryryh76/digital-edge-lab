import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_animation_assets as target


def fake_glb():
    json_chunk = b'{}  '
    chunk_type = 0x4E4F534A
    chunk = len(json_chunk).to_bytes(4, "little") + chunk_type.to_bytes(4, "little") + json_chunk
    return b"glTF" + (2).to_bytes(4, "little") + (12 + len(chunk)).to_bytes(4, "little") + chunk


def make_archive(glb):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("Unreal-Godot/UAL1_Standard.glb", glb)
        z.writestr("License.txt", "Creative Commons Zero 1.0 Universal")
        z.writestr("../outside.txt", "must not be extracted")
    return buffer.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class AnimationFetcherTests(unittest.TestCase):

    def test_ual2_glb_sha256_is_pinned(self):
        self.assertEqual(
            target.PACKS["ual2"]["glb_sha256"],
            "8cee20ab1bc55130092447e810e26df22dd2803eccc54f52137a7d54d7ab88a8",
        )
    def test_unknown_pack_is_rejected(self):
        with self.assertRaisesRegex(target.AssetFetchError, "unknown pack"):
            target.fetch_pack("invalid", Path("assets"), Path("cache"))

    def test_fetch_and_extract_pinned_glb_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = fake_glb()
            archive_bytes = make_archive(glb)
            pack = dict(target.PACKS["ual1"])
            pack.update(archive_sha256=target.sha256_bytes(archive_bytes), glb_sha256=target.sha256_bytes(glb))
            with patch.dict(target.PACKS, {"ual1": pack}):
                calls = []
                def fake_open(request, timeout):
                    calls.append(request)
                    if isinstance(request, target.urllib.request.Request):
                        return FakeResponse(json.dumps({"url": "https://signed.example/file"}).encode())
                    return FakeResponse(archive_bytes)
                asset = target.fetch_pack("ual1", root / "assets", root / "cache", urlopen=fake_open)
            self.assertEqual(asset.read_bytes(), glb)
            self.assertEqual(len(calls), 2)
            metadata = json.loads((root / "assets/UAL1_Standard.provenance.json").read_text())
            self.assertEqual(metadata["asset_sha256"], target.sha256_bytes(glb))
            self.assertEqual(metadata["license_id"], "CC0-1.0")
            self.assertTrue((root / "cache/UAL1_Standard.zip").exists())

    def test_bad_archive_hash_fails_before_zip_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = dict(target.PACKS["ual1"])
            pack["archive_sha256"] = "0" * 64
            archive_bytes = make_archive(fake_glb())
            with patch.dict(target.PACKS, {"ual1": pack}):
                def fake_open(request, timeout):
                    if isinstance(request, target.urllib.request.Request):
                        return FakeResponse(json.dumps({"url": "https://signed.example/file"}).encode())
                    return FakeResponse(archive_bytes)
                with self.assertRaisesRegex(target.AssetFetchError, "archive SHA-256 mismatch"):
                    target.fetch_pack("ual1", root / "assets", root / "cache", urlopen=fake_open)
            self.assertFalse((root / "cache/UAL1_Standard.zip").exists())

    def test_bad_zip_fails_and_no_asset_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = dict(target.PACKS["ual1"])
            bad_zip = b"not a zip file"
            pack["archive_sha256"] = target.sha256_bytes(bad_zip)
            with patch.dict(target.PACKS, {"ual1": pack}):
                with self.assertRaisesRegex(target.AssetFetchError, "not a readable ZIP"):
                    target._extract_expected_glb(pack, bad_zip, root / "asset.glb")
            self.assertFalse((root / "asset.glb").exists())

    def test_verified_cache_reuses_archive_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = fake_glb()
            archive_bytes = make_archive(glb)
            pack = dict(target.PACKS["ual1"])
            pack.update(archive_sha256=target.sha256_bytes(archive_bytes), glb_sha256=target.sha256_bytes(glb))
            cache = root / "cache"
            cache.mkdir()
            (cache / pack["archive_name"]).write_bytes(archive_bytes)
            with patch.dict(target.PACKS, {"ual1": pack}):
                def no_network(*args, **kwargs):
                    raise AssertionError("network used for verified cached archive")
                path = target.fetch_pack("ual1", root / "assets", cache, urlopen=no_network)
            self.assertEqual(path.read_bytes(), glb)

    def test_missing_glb_in_verified_zip_fails_closed(self):
        pack = dict(target.PACKS["ual1"])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("wrong/path.glb", fake_glb())
        with self.assertRaisesRegex(target.AssetFetchError, "expected exactly one"):
            target._extract_expected_glb(pack, buffer.getvalue(), Path("unused.glb"))


if __name__ == "__main__":
    unittest.main()
