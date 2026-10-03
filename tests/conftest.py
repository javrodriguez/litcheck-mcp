"""Shared fixtures: the offline guard, and the server pointed at recorded responses."""

import socket
from pathlib import Path

import pytest
from litcheck.transport import ReplayTransport

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "core" / "tests" / "fixtures"
FIXTURE_DAY = "2026-10-03T21:32:25Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test runs with sockets disabled: the recorded fixtures need no network."""

    def _blocked(*args, **kwargs):
        raise RuntimeError("network access attempted during an offline test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield


@pytest.fixture
def replay(monkeypatch, tmp_path):
    """The server's transport swapped for the recorded fixtures, its clock pinned to the
    fixtures' recorded date, and its log in a fresh temporary directory."""
    from litcheck_mcp import server

    transport = ReplayTransport(FIXTURES)
    monkeypatch.setattr(server, "transport", transport)
    monkeypatch.setattr(server, "clock", lambda: FIXTURE_DAY)
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("LITCHECK_LOG", str(log))
    return log
