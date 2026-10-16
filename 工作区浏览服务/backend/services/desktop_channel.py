"""One scoped desktop adapter connection per notification worker."""
import asyncio
import json
import os
from pathlib import Path


class DesktopChannel:
    def __init__(self):
        self.process = None
        self.identity = None
        self.sequence = 0
        self.lock = asyncio.Lock()

    async def call(self, data, operation, prompt=''):
        identity = (data.desktop.node, data.desktop.server, data.desktop.pipe,
                    data.desktop.caller_thread, data.thread_id)
        async with self.lock:
            if self.process is not None and self.identity != identity:
                await self.close()
            if self.process is None:
                bridge = Path(__file__).resolve().parents[2] / 'scripts/codex_task_bridge.mjs'
                self.process = await asyncio.create_subprocess_exec(data.desktop.node, str(bridge),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env={**os.environ, 'CODEX_APP_TOOLS_PIPE_PATH': data.desktop.pipe},
                    creationflags=0x08000000 if os.name == 'nt' else 0)
                self.identity = identity
                self.process.stdin.write((json.dumps({'server': data.desktop.server,
                    'caller': data.desktop.caller_thread, 'threadId': data.thread_id, 'operation': 'session'}) + '\n').encode())
            self.sequence += 1
            self.process.stdin.write((json.dumps({'id': self.sequence, 'operation': operation, 'prompt': prompt}) + '\n').encode())
            try:
                await self.process.stdin.drain()
                raw = await asyncio.wait_for(self.process.stdout.readline(), 40)
                response = json.loads(raw)
                if not isinstance(response, dict):
                    raise ValueError('Codex适配器返回非对象结果')
                if response.get('id') != self.sequence or response.get('error'):
                    raise OSError('Codex会话适配器响应不匹配或操作失败')
                result = response['result']
                if not isinstance(result, dict):
                    raise ValueError('Codex操作返回非对象结果')
                if result.get('isError'):
                    raise OSError('Codex拒绝本次会话操作')
                return result
            except (OSError, ValueError, KeyError, asyncio.TimeoutError):
                await self.close()
                raise

    async def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
            await process.wait()
