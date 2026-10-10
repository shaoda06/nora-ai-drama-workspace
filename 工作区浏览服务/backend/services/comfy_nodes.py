"""One persistent, read-only queue observer per configured ComfyUI endpoint."""
import asyncio
import json
import logging
from time import monotonic
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)
RETRY_DELAYS = (0, 1, 2, 5, 10, 30)
CONFIG_INTERVAL = 30


def initial_state():
    return {'connection': 'connecting', 'queue': [], 'running_count': None,
            'queued_count': None, 'updated_at': None, 'error': None, 'queue_error': None}


class RemoteQueues:
    def __init__(self, client, configured_urls, changed):
        self.client, self.configured_urls, self.changed = client, configured_urls, changed
        self.states = {}
        self.workers = {}
        self.manager = None

    async def start(self):
        await self.sync()
        self.manager = asyncio.create_task(self.follow_config())

    async def sync(self):
        urls = self.configured_urls()
        for url in list(self.workers):
            if url not in urls:
                worker = self.workers.pop(url)
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                del self.states[url]
        for url in urls:
            if url not in self.workers:
                self.states[url] = initial_state()
                self.workers[url] = asyncio.create_task(self.watch(url))
        self.changed()

    async def follow_config(self):
        while True:
            await asyncio.sleep(CONFIG_INTERVAL)
            await self.sync()
            await asyncio.gather(*(self.refresh(url) for url, state in tuple(self.states.items())
                                   if state['connection'] == 'connected'))

    async def close(self):
        workers = [*self.workers.values()]
        if self.manager is not None:
            workers.append(self.manager)
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    def update(self, url, **changes):
        self.states[url].update(changes)
        self.changed()

    async def refresh(self, url):
        try:
            result = await asyncio.to_thread(self.client.Client(url, 10).json, '/queue')
            queue = []
            for status, key in (('running', 'queue_running'), ('queued', 'queue_pending')):
                items = result[key]
                if not isinstance(items, list):
                    raise ValueError('远端队列字段必须为列表')
                for item in items:
                    if (not isinstance(item, list) or len(item) < 2 or not isinstance(item[0], (int, float))
                            or not isinstance(item[1], str)):
                        raise ValueError('远端队列缺少排序号或任务ID')
                # /queue returns the pending heap, not a fully sorted list.
                for index, item in enumerate(sorted(items, key=lambda item: item[0])):
                    # Do not expose workflow graphs, prompts or extra_data to browser readers.
                    queue.append({'prompt_id': item[1], 'status': status,
                                  'queue_position': index + 1 if status == 'queued' else None})
            self.update(url, queue=queue, running_count=len(result['queue_running']),
                        queued_count=len(result['queue_pending']), updated_at=self.client.now(), queue_error=None)
        except (self.client.ClientError, ValueError, KeyError, TypeError) as error:
            logger.warning('ComfyUI queue refresh failed for %s: %s', url, error)
            self.update(url, queue_error='队列读取失败，保留上次数据并重试')

    async def watch(self, url):
        parts = urlsplit(url)
        ws_url = urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc,
                            parts.path + '/ws', urlencode({'clientId': str(uuid.uuid4())}), ''))
        failures = 0
        while True:
            connected_at = None
            try:
                async with connect(ws_url, open_timeout=10, ping_interval=20, ping_timeout=20,
                                   close_timeout=5, max_size=2**22) as socket:
                    connected_at = monotonic()
                    self.update(url, connection='connecting', error=None)
                    await self.refresh(url)
                    self.update(url, connection='connected', error=None)
                    while True:
                        try:
                            raw = await asyncio.wait_for(socket.recv(), 30)
                        except asyncio.TimeoutError:
                            await self.refresh(url)
                            continue
                        if not isinstance(raw, str):
                            continue
                        message = json.loads(raw)
                        if not isinstance(message, dict):
                            raise ValueError('远端WebSocket消息必须为对象')
                        if message.get('type') == 'status':
                            await self.refresh(url)
            except (OSError, WebSocketException, asyncio.TimeoutError, ValueError) as error:
                logger.warning('ComfyUI node connection interrupted for %s: %s', url, error)
                if connected_at is not None and monotonic() - connected_at >= 60:
                    failures = 0
                delay = RETRY_DELAYS[min(failures, len(RETRY_DELAYS) - 1)]
                failures += 1
                self.update(url, connection='reconnecting', error='连接中断，正在自动重连')
                await asyncio.sleep(delay)
