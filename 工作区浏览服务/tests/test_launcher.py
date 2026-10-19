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
                patch.object(launcher.sys, 'platform', 'win32'), \
                patch.object(launcher, 'managed', return_value=True) as manager, \
                patch.object(launcher.os, 'kill') as kill, patch.object(launcher.time, 'sleep'):
            launcher.stop()
            manager.assert_called_once_with('stop')
            kill.assert_not_called()

    def test_legacy_stop_signals_only_the_verified_process(self):
        with patch.object(launcher, 'running', side_effect=[{'pid': 123}, None]), \
                patch.object(launcher.sys, 'platform', 'win32'), \
                patch.object(launcher, 'managed', return_value=False), patch.object(launcher.os, 'kill') as kill:
            launcher.stop()
            kill.assert_called_once_with(123, launcher.signal.SIGTERM)

    def test_mac_stop_waits_for_worker_exit_after_http_closes(self):
        with patch.object(launcher, 'running', side_effect=[{'pid': 123}, None, None]), \
                patch.object(launcher.sys, 'platform', 'darwin'), \
                patch.object(launcher, 'managed', return_value=True), \
                patch.object(launcher.os, 'kill', side_effect=[None, ProcessLookupError()]) as kill, \
                patch.object(launcher.time, 'sleep') as sleep:
            launcher.stop()
            self.assertEqual([call.args for call in kill.call_args_list], [(123, 0), (123, 0)])
            sleep.assert_called_once_with(.5)

    def test_failed_stop_prevents_restart(self):
        with patch.object(launcher, 'ensure_frontend', return_value='current'), \
                patch.object(launcher, 'running', return_value={'pid': 123}), \
                patch.object(launcher, 'stop', side_effect=RuntimeError('stop failed')), patch.object(launcher, 'managed') as manager:
            with self.assertRaisesRegex(RuntimeError, 'stop failed'):
                launcher.restart(False)
            manager.assert_not_called()

    def test_existing_service_no_browser_does_not_launch_again(self):
        with patch.object(launcher, 'ensure_frontend', return_value='current'), \
                patch.object(launcher, 'running', return_value={'pid': 123, 'version': 'current', 'ready': True}), \
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
                    patch.object(launcher, 'ensure_frontend', return_value='current'), \
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
                    patch.object(launcher, 'ensure_frontend', return_value='current'), \
                    patch.object(launcher, 'RUNTIME', root / 'runtime'), patch.object(launcher.socket, 'socket'), \
                    patch.object(launcher, 'running', side_effect=[None, {'ready': False}, {'ready': True}]), \
                    patch.object(launcher, 'managed') as manager, patch.object(launcher.webbrowser, 'open') as browser, \
                    patch.object(launcher.time, 'sleep'):
                launcher.start(False)
                manager.assert_called_once_with('start')
                browser.assert_not_called()


class FrontendBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.frontend = self.root / 'frontend'
        self.frontend.mkdir()
        (self.root / 'projects').mkdir()
        (self.frontend / 'package.json').write_text(json.dumps({'version': 'current'}), encoding='utf-8')
        override = patch.object(launcher, 'ROOT', self.root)
        override.start()
        self.addCleanup(override.stop)

    def built(self, version='current'):
        dist = self.frontend / 'dist'
        dist.mkdir(exist_ok=True)
        (dist / 'index.html').write_text('<html></html>', encoding='utf-8')
        (dist / 'release.json').write_text(json.dumps({'version': version}), encoding='utf-8')

    def test_missing_or_outdated_build_is_built_once(self):
        for state in ['missing', 'outdated', 'missing-index', 'missing-release']:
            with self.subTest(state=state):
                if state != 'missing':
                    self.built('old' if state == 'outdated' else 'current')
                    if state.startswith('missing-'):
                        (self.frontend / 'dist' / ('index.html' if state == 'missing-index' else 'release.json')).unlink()
                with patch.object(launcher.shutil, 'which', return_value='/tools/npm') as which, \
                        patch.object(launcher, 'command', side_effect=lambda *args, **kwargs: self.built()) as build:
                    self.assertEqual(launcher.ensure_frontend(), 'current')
                    build.assert_called_once_with(['/tools/npm', '--prefix', str(self.frontend), 'run', 'build'],
                                                  cwd=self.root, shell=launcher.sys.platform == 'win32')
                    launcher.ensure_frontend()
                    self.assertEqual(build.call_count, 1)
                    self.assertEqual(which.call_count, 1)

    def test_current_build_does_not_require_build_tools(self):
        self.built()
        with patch.object(launcher.shutil, 'which') as which, patch.object(launcher, 'command') as build:
            self.assertEqual(launcher.ensure_frontend(), 'current')
            which.assert_not_called()
            build.assert_not_called()

    def test_missing_npm_reports_setup_instead_of_starting(self):
        with patch.object(launcher.shutil, 'which', return_value=None), \
                patch.object(launcher, 'managed') as manager:
            with self.assertRaisesRegex(RuntimeError, '未找到npm'):
                launcher.start(False)
            manager.assert_not_called()

    def test_failed_build_keeps_existing_service_running(self):
        with patch.object(launcher.shutil, 'which', return_value='/tools/npm'), \
                patch.object(launcher, 'command', side_effect=RuntimeError('build failed')), \
                patch.object(launcher, 'stop') as stop, patch.object(launcher, 'managed') as manager:
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                launcher.restart(False)
            stop.assert_not_called()
            manager.assert_not_called()

    def test_successful_command_without_current_output_is_not_ready(self):
        with patch.object(launcher.shutil, 'which', return_value='/tools/npm'), \
                patch.object(launcher, 'command', return_value=''):
            with self.assertRaisesRegex(RuntimeError, '未生成与当前源码版本一致'):
                launcher.ensure_frontend()

    def test_start_updates_old_service_after_build_and_reuses_updated_service(self):
        events = []
        ready = {'version': 'current', 'ready': True}
        with patch.object(launcher, 'WORKSPACE', self.root), \
                patch.object(launcher, 'RUNTIME', self.root / 'runtime'), \
                patch.object(launcher.shutil, 'which', return_value='/tools/npm'), \
                patch.object(launcher, 'command', side_effect=lambda *args, **kwargs: (events.append('build'), self.built())), \
                patch.object(launcher, 'running', side_effect=[{'version': 'old', 'ready': False}, ready, ready]), \
                patch.object(launcher, 'stop', side_effect=lambda: events.append('stop')) as stop, \
                patch.object(launcher, 'managed', side_effect=lambda action: events.append(action)), \
                patch.object(launcher.socket, 'socket'):
            launcher.start(False)
            self.assertEqual(events, ['build', 'stop', 'start'])
            launcher.start(False)
            self.assertEqual(events, ['build', 'stop', 'start'])
            stop.assert_called_once()


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
