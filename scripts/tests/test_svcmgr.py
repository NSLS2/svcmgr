#!/usr/bin/env python3
"""Unit tests for svcmgr (pytest)."""

import socket
import subprocess
import threading
import time

import sys
import os

import pytest

# Add parent directory to path so we can import svcmgr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import svcmgr


SERVICES = ["camserver", "xspd"]


class MockCompletedProcess:
    """Lightweight stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Fixture: monkeypatch subprocess.run used by run_systemctl
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_systemctl(monkeypatch):
    """Fixture that patches subprocess.run to simulate systemctl calls.

    Returns a callable record object. Set .return_value or .side_effect
    to control behaviour. Calls are recorded in .calls.
    """
    class Recorder:
        def __init__(self):
            self.calls = []
            self.return_value = MockCompletedProcess(0, "active\n", "")
            self.side_effect = None

        def __call__(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            if self.side_effect is not None:
                raise self.side_effect
            return self.return_value

    recorder = Recorder()
    monkeypatch.setattr(svcmgr.subprocess, "run", recorder)
    return recorder


# ---------------------------------------------------------------------------
# handle_command tests
# ---------------------------------------------------------------------------

def test_help():
    result = svcmgr.handle_command("help", SERVICES)
    assert "Available commands" in result
    assert "status" in result
    assert "start" in result
    assert "restart" in result


def test_list():
    result = svcmgr.handle_command("list", SERVICES)
    assert result == "camserver\nxspd"


def test_empty_command():
    result = svcmgr.handle_command("", SERVICES)
    assert "ERROR" in result


def test_unknown_command():
    result = svcmgr.handle_command("foobar", SERVICES)
    assert "ERROR" in result
    assert "unknown command" in result


def test_case_insensitive_command():
    result = svcmgr.handle_command("HELP", SERVICES)
    assert "Available commands" in result


@pytest.mark.parametrize("cmd", ["start", "stop", "restart"])
def test_missing_service_name(cmd):
    result = svcmgr.handle_command(cmd, SERVICES)
    assert "ERROR" in result
    assert "requires a service name" in result


@pytest.mark.parametrize("cmd", ["start", "stop", "restart", "status"])
def test_unmanaged_service(cmd):
    result = svcmgr.handle_command("{} unknown_svc".format(cmd), SERVICES)
    assert "ERROR" in result
    assert "not a managed service" in result


def test_start_managed_service(mock_systemctl):
    result = svcmgr.handle_command("start camserver", SERVICES)
    assert "OK" in result
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "start", "camserver"]


def test_stop_managed_service(mock_systemctl):
    result = svcmgr.handle_command("stop xspd", SERVICES)
    assert "OK" in result
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "stop", "xspd"]


def test_restart_managed_service(mock_systemctl):
    result = svcmgr.handle_command("restart camserver", SERVICES)
    assert "OK" in result
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "restart", "camserver"]


def test_start_failure(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(1, "", "Failed to start")
    result = svcmgr.handle_command("start camserver", SERVICES)
    assert "FAIL" in result
    assert "Failed to start" in result


def test_status_single_service(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    svcmgr.handle_command("status camserver", SERVICES)
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "status", "camserver"]


def test_status_all_services(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    result = svcmgr.handle_command("status", SERVICES)
    assert "camserver: active" in result
    assert "xspd: active" in result
    assert len(mock_systemctl.calls) == 2


# ---------------------------------------------------------------------------
# run_systemctl tests
# ---------------------------------------------------------------------------

def test_run_systemctl_success(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    rc, output = svcmgr.run_systemctl("is-active", "camserver")
    assert rc == 0
    assert output == "active"


def test_run_systemctl_failure(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(3, "", "inactive\n")
    rc, output = svcmgr.run_systemctl("is-active", "camserver")
    assert rc == 3
    assert output == "inactive"


def test_run_systemctl_timeout(mock_systemctl):
    mock_systemctl.side_effect = subprocess.TimeoutExpired(
        cmd="systemctl", timeout=30
    )
    rc, output = svcmgr.run_systemctl("start", "camserver")
    assert rc == 1
    assert "Timeout" in output


def test_run_systemctl_os_error(mock_systemctl):
    mock_systemctl.side_effect = OSError("no such file")
    rc, output = svcmgr.run_systemctl("start", "camserver")
    assert rc == 1
    assert "no such file" in output


# ---------------------------------------------------------------------------
# get_service_status tests
# ---------------------------------------------------------------------------

def test_get_service_status_active(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    assert svcmgr.get_service_status("camserver") == "active"


def test_get_service_status_inactive(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(3, "inactive\n", "")
    assert svcmgr.get_service_status("camserver") == "inactive"


def test_get_service_status_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(1, "", "")
    assert svcmgr.get_service_status("camserver") == "unknown"


# ---------------------------------------------------------------------------
# handle_client integration tests (real socket pair)
# ---------------------------------------------------------------------------

def _run_client_session(commands):
    """Send commands to handle_client via a socketpair, return all received data."""
    server_sock, client_sock = socket.socketpair()
    t = threading.Thread(
        target=svcmgr.handle_client,
        args=(server_sock, ("test", 0), SERVICES),
        daemon=True,
    )
    t.start()

    received = b""
    for cmd in commands:
        client_sock.sendall((cmd + "\n").encode())
        time.sleep(0.1)
        try:
            received += client_sock.recv(4096)
        except OSError:
            break

    client_sock.close()
    t.join(timeout=2)
    return received.decode()


def test_client_list_command():
    result = _run_client_session(["list"])
    assert "camserver" in result
    assert "xspd" in result


def test_client_help_command():
    result = _run_client_session(["help"])
    assert "Available commands" in result


def test_client_quit_command():
    result = _run_client_session(["quit"])
    assert "BYE" in result


def test_client_unknown_command():
    result = _run_client_session(["bogus"])
    assert "ERROR" in result


def test_client_status_all(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    result = _run_client_session(["status"])
    assert "camserver: active" in result
    assert "xspd: active" in result


def test_client_multiple_commands():
    result = _run_client_session(["help", "list", "quit"])
    assert "Available commands" in result
    assert "camserver" in result
    assert "BYE" in result


# ---------------------------------------------------------------------------
# main() root check
# ---------------------------------------------------------------------------

def test_refuses_root(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["svcmgr.py", "camserver"])
    with pytest.raises(SystemExit):
        svcmgr.main()
