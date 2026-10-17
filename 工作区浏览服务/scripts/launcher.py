"""Start this workspace through the current user's operating-system manager."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'
CONFIG = RUNTIME / 'service.json'
settings = json.loads(CONFIG.read_text('utf-8-sig')) if CONFIG.is_file() else {}
WORKSPACE = Path(settings.get('workspace', ROOT.parent)).resolve()
PORT = int(settings.get('port', 8782))
ENVIRONMENT = settings.get('environment', 'production')
URL = f'http://127.0.0.1:{PORT}'


def command(arguments, **options):
    result = subprocess.run(arguments, capture_output=True, text=True, encoding='utf-8', **options)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'{arguments[0]} failed')
    return result.stdout


def windows_task(action):
    script = (ROOT / 'scripts/windows_service.ps1').read_text('utf-8-sig')
    output = command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                     env={**os.environ, 'NORA_LAUNCH_ACTION': action, 'NORA_LAUNCH_ROOT': str(ROOT),
                          'NORA_LAUNCH_PORT': str(PORT)}, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(output)


def mac_task(action):
    label = f'local.nora.workspace-browser.{PORT}'
    target = f'gui/{os.getuid()}/{label}'
    path = Path.home() / 'Library/LaunchAgents' / f'{label}.plist'
    arguments = [str(ROOT / '.venv/bin/python'), '-B', str(ROOT / 'scripts/launcher.py'), 'serve']
    if path.exists():
        existing = plistlib.loads(path.read_bytes())
        if existing['ProgramArguments'] != arguments or existing['WorkingDirectory'] != str(ROOT):
            raise RuntimeError(f'系统后台项 {label} 属于其他目录，未覆盖。')
    loaded = any(line.split()[-1:] == [label] for line in command(['launchctl', 'list']).splitlines())
    if loaded:
        if not path.exists():
            raise RuntimeError(f'系统后台项 {label} 缺少本工作区定义，未操作。')
        command(['launchctl', 'bootout', target])
    if action == 'stop':
        return loaded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps({
        'Label': label, 'ProgramArguments': arguments, 'WorkingDirectory': str(ROOT),
        'EnvironmentVariables': {'PATH': os.environ.get('PATH', os.defpath)},
        'RunAtLoad': False, 'KeepAlive': False,
        'StandardOutPath': str(RUNTIME / 'server.log'), 'StandardErrorPath': str(RUNTIME / 'server.log'),
    }))
    command(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)])
    command(['launchctl', 'kickstart', target])
    return True


def managed(action):
    if sys.platform == 'win32':
        return windows_task(action)['stopped'] if action == 'stop' else windows_task(action)
    if sys.platform == 'darwin':
        return mac_task(action)
    raise RuntimeError('系统托管启动目前支持Windows和macOS。')


def serve():
    """Foreground worker, invoked only by Task Scheduler or launchd."""
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ.update(NORA_WORKSPACE=str(WORKSPACE), NORA_SERVICE_ENV=ENVIRONMENT, NORA_SERVICE_PORT=str(PORT))
    sys.stdout = sys.stderr = (RUNTIME / 'server.log').open('a', encoding='utf-8', buffering=1)
    import uvicorn
    uvicorn.run('backend.main:app', host='0.0.0.0', port=PORT)


def running():
    try:
        with urlopen(URL + '/api/service', timeout=2) as response:
            data = json.load(response)
    except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None
    if data.get('app') != 'nora-workspace-browser':
        return None
    tool = Path(data.get('tool', Path(data['workspace']) / '工作区浏览服务')).resolve()
    return data if Path(data['workspace']).resolve() == WORKSPACE and tool == ROOT else None


def start(open_browser=True):
    if running():
        if open_browser:
            webbrowser.open(URL)
        return
    if not (WORKSPACE / 'projects').is_dir():
        raise RuntimeError('资料工作区缺少projects目录，请检查runtime/service.json中的workspace。')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('前端尚未构建，请按工作区浏览服务/README.md完成安装。')
    with socket.socket() as probe:
        try:
            probe.bind(('0.0.0.0', PORT))
        except OSError as error:
            raise RuntimeError(f'{PORT}端口已被其他程序占用；未停止该程序。请查看工作区浏览服务/README.md。') from error
    RUNTIME.mkdir(exist_ok=True)
    managed('start')
    for _ in range(40):
        data = running()
        if data and data.get('ready'):
            if open_browser:
                webbrowser.open(URL)
            return
        time.sleep(.5)
    raise RuntimeError('服务未在20秒内就绪，请查看runtime/server.log及系统后台项的运行结果。')


def stop():
    data = running()
    if not data:
        raise RuntimeError('未找到本工作区的浏览服务；没有停止其他程序。')
    if not managed('stop'):
        # Migrate an earlier directly launched process after checking its identity.
        os.kill(data['pid'], signal.SIGTERM)
    for _ in range(40):
        if not running():
            return
        time.sleep(.5)
    raise RuntimeError('服务未在20秒内停止，未启动第二个进程。')


def restart(open_browser=True):
    if running():
        stop()
    start(open_browser)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'serve'])
    parser.add_argument('--no-browser', action='store_true', help='Start or restart without opening a browser (Agent releases).')
    args = parser.parse_args()
    try:
        if args.action == 'serve':
            serve()
        elif args.action == 'stop':
            stop()
        else:
            (start if args.action == 'start' else restart)(not args.no_browser)
    except (OSError, RuntimeError) as error:
        if os.name == 'nt' and not args.no_browser and args.action != 'serve':
            import tkinter.messagebox
            tkinter.messagebox.showerror('Nora 工作区浏览服务', str(error))
        else:
            print(str(error), file=sys.stderr)
        sys.exit(1)
