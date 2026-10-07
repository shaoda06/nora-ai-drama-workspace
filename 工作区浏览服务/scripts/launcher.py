"""Double-click entry; launches only this workspace's backend."""
import argparse
import json
import os
from pathlib import Path
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


def start():
    if running():
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
    python = ROOT / '.venv/Scripts/python.exe' if os.name == 'nt' else ROOT / '.venv/bin/python'
    environment = {**os.environ, 'NORA_WORKSPACE': str(WORKSPACE), 'NORA_SERVICE_ENV': ENVIRONMENT}
    with (RUNTIME / 'server.log').open('ab') as output:
        process = subprocess.Popen([str(python), '-m', 'uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', str(PORT)],
                                   cwd=ROOT, env=environment, stdout=output, stderr=output, stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(40):
        if process.poll() is not None:
            raise RuntimeError('服务启动失败，请查看工作区浏览服务/runtime/server.log。')
        if running():
            webbrowser.open(URL)
            return
        time.sleep(.5)
    raise RuntimeError('服务未在20秒内响应，请查看工作区浏览服务/runtime/server.log。')


def stop():
    data = running()
    if not data:
        raise RuntimeError('未找到本工作区的浏览服务；没有停止其他程序。')
    os.kill(data['pid'], signal.SIGTERM)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop'])
    args = parser.parse_args()
    try:
        start() if args.action == 'start' else stop()
    except (OSError, RuntimeError) as error:
        if os.name == 'nt':
            import tkinter.messagebox
            tkinter.messagebox.showerror('Nora 工作区浏览服务', str(error))
        else:
            print(str(error), file=sys.stderr)
        sys.exit(1)
