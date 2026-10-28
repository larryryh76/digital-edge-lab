import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pipeline


class PrepareDirsStateSafetyTests(unittest.TestCase):
    def test_preserves_operator_database_and_unknown_state_files(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "output"
            out.mkdir()
            db = out / "operator.sqlite3"
            db.write_bytes(b"persistent operator state")
            extra = out / "custom-state.json"
            extra.write_text('{"keep": true}', encoding="utf-8")
            stale = out / "run-report.json"
            stale.write_text('{"stale": true}', encoding="utf-8")
            with patch.object(pipeline, "OUT", out):
                pipeline.prepare_dirs()
            self.assertEqual(db.read_bytes(), b"persistent operator state")
            self.assertEqual(extra.read_text(encoding="utf-8"), '{"keep": true}')
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
