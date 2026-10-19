"""HTTP tests exercise routes without starting the production task service."""
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import main
from backend.services.request_diagnostics import RequestDiagnostics


@asynccontextmanager
async def without_background_tasks(app):
    yield


class HttpTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Even tests that omit lifespan must never write production diagnostics.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        diagnostics = RequestDiagnostics(Path(directory.name))
        self.addCleanup(diagnostics.close_logs)
        monitor = patch.object(main.app.state, 'request_diagnostics', diagnostics, create=True)
        monitor.start()
        self.addCleanup(monitor.stop)
        override = patch.object(main.app.router, 'lifespan_context', without_background_tasks)
        override.start()
        self.addCleanup(override.stop)
