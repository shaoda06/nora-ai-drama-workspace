"""HTTP tests exercise routes without starting the production task service."""
from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch

from backend import main


@asynccontextmanager
async def without_background_tasks(app):
    yield


class HttpTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        override = patch.object(main.app.router, 'lifespan_context', without_background_tasks)
        override.start()
        self.addCleanup(override.stop)
