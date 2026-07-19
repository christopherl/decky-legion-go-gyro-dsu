import importlib
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
sys.modules.setdefault("decky", SimpleNamespace(logger=Mock()))
plugin_module = importlib.import_module("main")


class ServiceStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_systemctl_uses_absolute_noninteractive_command(self):
        completed = CompletedProcess([], 0, "loaded\n", "")
        with patch.object(plugin_module.subprocess, "run", return_value=completed) as run:
            result = await plugin_module.run_systemctl(
                "show", plugin_module.SERVICE_NAME
            )

        self.assertEqual(result, (0, "loaded", ""))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/systemctl")
        self.assertIn("--no-pager", command)
        self.assertIn("--no-ask-password", command)

    async def test_reports_active_installed_service(self):
        responses = [
            (0, "loaded", ""),
            (0, "active", ""),
        ]
        with patch.object(
            plugin_module, "run_systemctl", AsyncMock(side_effect=responses)
        ):
            status = await plugin_module.read_service_status()

        self.assertTrue(status.installed)
        self.assertTrue(status.active)
        self.assertEqual(status.state, "active")

    async def test_reports_missing_service(self):
        with patch.object(
            plugin_module,
            "run_systemctl",
            AsyncMock(return_value=(1, "not-found", "Unit not found")),
        ):
            status = await plugin_module.read_service_status()

        self.assertFalse(status.installed)
        self.assertFalse(status.active)
        self.assertEqual(status.state, "not-installed")

    async def test_toggle_starts_only_the_fixed_service(self):
        responses = [
            (0, "loaded", ""),
            (3, "inactive", ""),
            (0, "", ""),
            (0, "loaded", ""),
            (0, "active", ""),
        ]
        systemctl = AsyncMock(side_effect=responses)
        with patch.object(plugin_module, "run_systemctl", systemctl):
            result = await plugin_module.Plugin().set_service_enabled(True)

        self.assertTrue(result["active"])
        self.assertEqual(
            systemctl.await_args_list[2].args,
            ("start", plugin_module.SERVICE_NAME),
        )

    async def test_rejects_non_boolean_toggle_value(self):
        result = await plugin_module.Plugin().set_service_enabled("yes")
        self.assertEqual(result["state"], "error")
        self.assertIn("boolean", result["error"])


if __name__ == "__main__":
    unittest.main()
