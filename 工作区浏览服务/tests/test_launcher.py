import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
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

    def test_stop_uses_manager_and_waits_for_service_to_leave(self):
        with patch.object(launcher, 'running', side_effect=[{'pid': 123}, {'pid': 123}, None]), \
                patch.object(launcher, 'managed', return_value=True) as manager, \
                patch.object(launcher.os, 'kill') as kill, patch.object(launcher.time, 'sleep'):
            launcher.stop()
            manager.assert_called_once_with('stop')
            kill.assert_not_called()

    def test_legacy_stop_signals_only_the_verified_process(self):
        with patch.object(launcher, 'running', side_effect=[{'pid': 123}, None]), \
                patch.object(launcher, 'managed', return_value=False), patch.object(launcher.os, 'kill') as kill:
            launcher.stop()
            kill.assert_called_once_with(123, launcher.signal.SIGTERM)

    def test_failed_stop_prevents_restart(self):
        with patch.object(launcher, 'running', return_value={'pid': 123}), \
                patch.object(launcher, 'stop', side_effect=RuntimeError('stop failed')), patch.object(launcher, 'start') as start:
            with self.assertRaisesRegex(RuntimeError, 'stop failed'):
                launcher.restart(False)
            start.assert_not_called()

    def test_existing_service_no_browser_does_not_launch_again(self):
        with patch.object(launcher, 'running', return_value={'pid': 123}), \
                patch.object(launcher, 'managed') as manager, patch.object(launcher.webbrowser, 'open') as browser:
            launcher.start(False)
            manager.assert_not_called()
            browser.assert_not_called()

    def test_foreign_port_is_not_taken_over(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'projects').mkdir()
            (root / 'frontend/dist').mkdir(parents=True)
            (root / 'frontend/dist/index.html').touch()
            with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'WORKSPACE', root), \
                    patch.object(launcher, 'running', return_value=None), patch.object(launcher.socket, 'socket') as socket, \
                    patch.object(launcher, 'managed') as manager:
                socket.return_value.__enter__.return_value.bind.side_effect = OSError('in use')
                with self.assertRaisesRegex(RuntimeError, '未停止该程序'):
                    launcher.start(False)
                manager.assert_not_called()

    def test_start_waits_for_ready_instead_of_just_a_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'projects').mkdir()
            (root / 'frontend/dist').mkdir(parents=True)
            (root / 'frontend/dist/index.html').touch()
            with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'WORKSPACE', root), \
                    patch.object(launcher, 'RUNTIME', root / 'runtime'), patch.object(launcher.socket, 'socket'), \
                    patch.object(launcher, 'running', side_effect=[None, {'ready': False}, {'ready': True}]), \
                    patch.object(launcher, 'managed') as manager, patch.object(launcher.webbrowser, 'open') as browser, \
                    patch.object(launcher.time, 'sleep'):
                launcher.start(False)
                manager.assert_called_once_with('start')
                browser.assert_not_called()


class MacManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.root = self.home / '工作区 with spaces/工作区浏览服务'
        self.root.mkdir(parents=True)
        self.label = f'local.nora.workspace-browser.{launcher.PORT}'
        self.plist = self.home / f'Library/LaunchAgents/{self.label}.plist'
        for override in (patch.object(launcher.Path, 'home', return_value=self.home),
                         patch.object(launcher, 'ROOT', self.root),
                         patch.object(launcher.os, 'getuid', return_value=501, create=True)):
            override.start()
            self.addCleanup(override.stop)

    def test_manual_job_uses_local_foreground_worker(self):
        with patch.object(launcher, 'command', return_value='') as command:
            launcher.mac_task('start')
        definition = plistlib.loads(self.plist.read_bytes())
        self.assertFalse(definition['RunAtLoad'])
        self.assertFalse(definition['KeepAlive'])
        self.assertNotIn('StartInterval', definition)
        self.assertNotIn('StartCalendarInterval', definition)
        self.assertEqual(definition['ProgramArguments'], [str(self.root / '.venv/bin/python'), '-B',
                                                         str(self.root / 'scripts/launcher.py'), 'serve'])
        self.assertEqual(command.call_args_list[-2].args[0], ['launchctl', 'bootstrap', 'gui/501', str(self.plist)])
        self.assertEqual(command.call_args_list[-1].args[0], ['launchctl', 'kickstart', f'gui/501/{self.label}'])

    def test_stop_unloads_job_instead_of_leaving_it_restartable(self):
        with patch.object(launcher, 'command', return_value=''):
            launcher.mac_task('start')
        with patch.object(launcher, 'command', side_effect=[f'123\t0\t{self.label}\n', '']) as command:
            self.assertTrue(launcher.mac_task('stop'))
        command.assert_called_with(['launchctl', 'bootout', f'gui/501/{self.label}'])

    def test_other_workspace_definition_is_not_replaced_or_unloaded(self):
        self.plist.parent.mkdir(parents=True)
        original = plistlib.dumps({'WorkingDirectory': '/other/tool', 'ProgramArguments': ['/other/python']})
        self.plist.write_bytes(original)
        with patch.object(launcher, 'command') as command:
            with self.assertRaisesRegex(RuntimeError, '属于其他目录'):
                launcher.mac_task('start')
            command.assert_not_called()
        self.assertEqual(self.plist.read_bytes(), original)

    def test_loaded_job_without_owned_definition_is_not_unloaded(self):
        with patch.object(launcher, 'command', return_value=f'123\t0\t{self.label}\n') as command:
            with self.assertRaisesRegex(RuntimeError, '缺少本工作区定义'):
                launcher.mac_task('stop')
            self.assertEqual(command.call_count, 1)

    def test_manager_error_is_reported_without_direct_process_fallback(self):
        with patch.object(launcher, 'command', side_effect=RuntimeError('launchctl denied')):
            with self.assertRaisesRegex(RuntimeError, 'launchctl denied'):
                launcher.mac_task('start')


if __name__ == '__main__':
    unittest.main()
