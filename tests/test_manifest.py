import json
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_requests_root_for_system_service_control(self):
        manifest = json.loads((PROJECT_DIR / "plugin.json").read_text())
        self.assertIn("root", manifest["flags"])
        self.assertNotIn("_root", manifest["flags"])


if __name__ == "__main__":
    unittest.main()
