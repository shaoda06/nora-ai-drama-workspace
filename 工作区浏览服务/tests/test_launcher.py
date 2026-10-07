import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('browser_launcher', Path(__file__).resolve().parents[1] / 'scripts/launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherIdentityTests(unittest.TestCase):
    def probe(self, payload, tool, workspace):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(launcher, 'ROOT', tool), patch.object(launcher, 'WORKSPACE', workspace), patch.object(launcher, 'urlopen', return_value=response):
            return launcher.running()

    def test_shared_data_does_not_make_production_the_development_service(self):
        workspace = Path('shared').resolve()
        production = workspace / '工作区浏览服务'
        development = Path('development/工作区浏览服务').resolve()
        payload = dict(app='nora-workspace-browser', workspace=str(workspace), tool=str(production), pid=123)
        self.assertIsNone(self.probe(payload, development, workspace))
        self.assertEqual(self.probe(payload, production, workspace), payload)

    def test_old_production_identity_is_only_accepted_at_original_tool_directory(self):
        workspace = Path('shared').resolve()
        payload = dict(app='nora-workspace-browser', workspace=str(workspace), pid=123)
        self.assertIsNone(self.probe(payload, Path('development/工作区浏览服务').resolve(), workspace))
        self.assertEqual(self.probe(payload, workspace / '工作区浏览服务', workspace), payload)

    def test_connection_reset_while_service_stops_is_not_a_running_service(self):
        with patch.object(launcher, 'urlopen', side_effect=ConnectionResetError(10054, 'connection closed')):
            self.assertIsNone(launcher.running())

    def test_stop_never_signals_a_service_with_a_different_identity(self):
        with patch.object(launcher, 'running', return_value=None), patch.object(launcher.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, '没有停止其他程序'):
                launcher.stop()
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
