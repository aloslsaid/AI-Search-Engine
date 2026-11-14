"""Test helpers: put the project on sys.path and provide fakes.

If aiohttp is not installed (e.g. a minimal CI box), a tiny stub is registered
so the HTTP clients can still be tested with fake sessions. With aiohttp
installed the real library is used.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - depends on environment
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientSession:
        pass

    class FormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append((name, value, kwargs))

    stub.ClientError = ClientError
    stub.ClientTimeout = ClientTimeout
    stub.ClientSession = ClientSession
    stub.FormData = FormData
    sys.modules["aiohttp"] = stub

import aiohttp as _aiohttp  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, json_data=None, text_data="", json_error=False):
        self.status = status
        self._json = json_data
        self._text = text_data
        self._json_error = json_error

    async def json(self, content_type=None):
        if self._json_error:
            raise ValueError("not json")
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Plays back a queue of responses (or exceptions) for get/post calls."""

    def __init__(self, *queue):
        self.queue = list(queue)
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)


ClientError = _aiohttp.ClientError
