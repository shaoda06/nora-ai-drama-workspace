"""Bounded, local diagnostics; never cancel requests or change production tasks."""
import asyncio
from datetime import datetime, timezone
import faulthandler
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time


class RequestDiagnostics:
    def __init__(self, directory: Path, *, slow_seconds=2, stalled_seconds=15):
        self.directory = directory
        self.slow_seconds, self.stalled_seconds = slow_seconds, stalled_seconds
        self.lock = threading.Lock()
        self.pending = {}
        self.sequence = 0
        self.last_heartbeat = time.monotonic()
        self.stalled_since = None
        self.stop_event = threading.Event()
        self.log = logging.getLogger(__name__ + '.' + str(id(self)))
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        self.handler = RotatingFileHandler(directory / 'request-diagnostics.jsonl',
            maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8', delay=True)
        self.log.addHandler(self.handler)

    def write(self, event, **fields):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.log.info(json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                                     'pid': os.getpid(), 'event': event, **fields}, ensure_ascii=False))
        except OSError:
            # Keep the original request intact if the diagnostic directory is
            # unavailable, while preserving an error in the normal server log.
            logging.getLogger(__name__).exception('Request diagnostic write failed')

    def begin(self, method, path):
        with self.lock:
            self.sequence += 1
            key = self.sequence
            self.pending[key] = {'request_id': key, 'method': method, 'path': path,
                                 'started': time.monotonic()}
        return key

    def finish(self, key, status=None):
        with self.lock:
            item = self.pending.pop(key, None)
        if item is not None:
            elapsed = time.monotonic() - item.pop('started')
            if elapsed >= self.slow_seconds:
                self.write('slow_request', **item, seconds=round(elapsed, 3), status=status,
                           phase='response_headers' if status is not None else 'ended_without_headers')

    def check_stalls(self):
        now = time.monotonic()
        with self.lock:
            overdue = [dict(request_id=item['request_id'], method=item['method'], path=item['path'],
                            seconds=round(now - item['started'], 3)) for item in self.pending.values()
                       if now - item['started'] >= self.stalled_seconds]
            lag = now - self.last_heartbeat
        if overdue or lag >= self.stalled_seconds:
            if self.stalled_since is None:
                self.stalled_since = now
                self.write('service_stalled', loop_lag_seconds=round(lag, 3),
                           overdue_count=len(overdue), requests=overdue[:20])
                self.dump_stacks()
        elif self.stalled_since is not None:
            self.write('service_recovered', seconds=round(now - self.stalled_since, 3))
            self.stalled_since = None

    def dump_stacks(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / 'request-stacks.log'
        if target.exists() and target.stat().st_size >= 2 * 1024 * 1024:
            target.replace(target.with_suffix('.log.1'))
        with target.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
                'threads': [{'name': item.name, 'ident': hex(item.ident) if item.ident else None,
                             'native_id': item.native_id} for item in threading.enumerate()]}, ensure_ascii=False) + '\n')
            stream.flush()
            faulthandler.dump_traceback(file=stream, all_threads=True)

    async def heartbeat(self):
        while True:
            with self.lock:
                self.last_heartbeat = time.monotonic()
            await asyncio.sleep(1)

    def watch(self):
        while not self.stop_event.wait(1):
            try:
                self.check_stalls()
            except OSError:
                # A diagnostic disk failure must not stop the monitor silently.
                logging.getLogger(__name__).exception('Request diagnostic write failed')

    def start(self):
        self.heartbeat_task = asyncio.create_task(self.heartbeat())
        self.worker = threading.Thread(target=self.watch, name='nora-request-diagnostics', daemon=True)
        self.worker.start()

    def close_logs(self):
        self.handler.close()
        self.log.removeHandler(self.handler)

    async def close(self):
        self.stop_event.set()
        self.heartbeat_task.cancel()
        await asyncio.gather(self.heartbeat_task, return_exceptions=True)
        await asyncio.to_thread(self.worker.join)
        self.close_logs()


class RequestDiagnosticsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        monitor = scope['app'].state.request_diagnostics
        key = monitor.begin(scope['method'], scope['path'])

        async def response(message):
            if message['type'] == 'http.response.start':
                # SSE and large media downloads remain open normally. Measure
                # time to headers, not the lifetime of their response streams.
                monitor.finish(key, message['status'])
            await send(message)

        try:
            await self.app(scope, receive, response)
        finally:
            monitor.finish(key)
