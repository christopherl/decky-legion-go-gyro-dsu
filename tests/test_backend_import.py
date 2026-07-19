import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class BackendImportTests(unittest.TestCase):
    def test_main_loads_sibling_module_outside_plugin_working_directory(self):
        script = textwrap.dedent(
            f"""
            import importlib.util
            import logging
            import sys
            import types

            plugin_dir = {str(PROJECT_DIR)!r}
            sys.path = [path for path in sys.path if path not in ("", plugin_dir)]
            sys.modules["decky"] = types.SimpleNamespace(
                DECKY_PLUGIN_DIR=plugin_dir,
                logger=logging.getLogger("decky-test"),
            )
            spec = importlib.util.spec_from_file_location(
                "decky_legion_backend", f"{{plugin_dir}}/main.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            assert module.DSUMotionClient.__module__ == "dsu_client"
            """
        )

        with tempfile.TemporaryDirectory() as working_directory:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=working_directory,
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
