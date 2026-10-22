"""Read a local Codex thread name without resuming it or starting a turn.

Protocol: https://learn.chatgpt.com/docs/app-server#read-a-stored-thread-without-resuming
"""
import asyncio
import json


async def read_thread_name(cli: str, thread_id: str) -> str:
    process = await asyncio.create_subprocess_exec(
        cli, 'app-server', '--listen', 'stdio://', stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        async with asyncio.timeout(20):
            async def request(sequence, method, params):
                process.stdin.write((json.dumps({'id': sequence, 'method': method, 'params': params}) + '\n').encode())
                await process.stdin.drain()
                while raw := await process.stdout.readline():
                    message = json.loads(raw)
                    if message.get('id') == sequence:
                        if 'error' in message:
                            raise OSError(f'Codex {method} failed: {message["error"]}')
                        return message['result']
                raise OSError('Codex会话名称读取连接提前关闭')

            await request(1, 'initialize', {'clientInfo': {
                'name': 'nora-task-session-name', 'title': 'Nora task session name', 'version': '1.0.0'}})
            process.stdin.write(b'{"method":"initialized"}\n')
            thread = (await request(2, 'thread/read', {'threadId': thread_id, 'includeTurns': False}))['thread']
            if thread['id'] != thread_id:
                raise ValueError('Codex返回的来源会话编号不匹配')
            name = thread.get('name')
            if not isinstance(name, str) or not name.strip():
                raise ValueError('来源会话尚未命名')
            return name.strip()
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            process.kill()
            await process.wait()
