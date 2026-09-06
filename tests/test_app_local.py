"""Real desktop integration and allowlisted feedback tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import feedback_bundle


class AppTests(unittest.TestCase):
    def test_feedback_never_copies_raw_files_or_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "secret.json").write_text('{"key":"SUPER_SECRET"}')
            (root / "picks").mkdir()
            (root / "picks" / "picks_corrupt.json").write_text('{"key":"SUPER_SECRET"}')
            target = feedback_bundle.build(root, root / "feedback.zip")
            with zipfile.ZipFile(target) as z:
                self.assertEqual(set(z.namelist()), {"diagnostics.json", "README.txt"})
                self.assertNotIn(b"SUPER_SECRET", b"".join(z.read(n) for n in z.namelist()))
                self.assertEqual(json.loads(z.read("diagnostics.json"))["rejected_pick_files"], 1)

    def test_source_key_fields_exist_masked_and_do_not_persist(self):
        import tkinter as tk
        try:
            probe = tk.Tk(); probe.destroy()
        except tk.TclError:
            if os.environ.get("MONEYPRINTER_REQUIRE_GUI_TESTS"):
                self.fail("GUI display required")
            self.skipTest("no display")
        import app
        import gui
        with tempfile.TemporaryDirectory() as tmp, patch.object(gui, "SETTINGS_FILE", Path(tmp) / "settings.json"), patch.object(gui, "migrate_legacy", return_value={"copied": 0, "errors": []}), patch.object(app.ResearchApp, "_poll", return_value=None):
            window = app.ResearchApp()
            try:
                window.data_sources(); window.update()
                self.assertIn("FRED_API_KEY", window.source_credentials)
                window.source_credentials["FRED_API_KEY"].set("SUPER_SECRET")
                window._save_settings()
                self.assertNotIn("SUPER_SECRET", (Path(tmp) / "settings.json").read_text())
                self.assertNotIn("FRED_API_KEY", (Path(tmp) / "settings.json").read_text())
                window.theme_var.set("dark"); window._apply_theme(); window.update()
            finally:
                window.destroy()


if __name__ == "__main__":
    unittest.main()
