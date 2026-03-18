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
<<<<<<< Updated upstream
    svcmgr.handle_command("status camserver", SERVICES)
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "status", "camserver"]
=======
    result = svcmgr.handle_command("status camserver", SERVICES)
    assert result == "Active"
    assert len(mock_systemctl.calls) == 1
    assert mock_systemctl.calls[0][0][0] == ["systemctl", "show", "-p", "ActiveState", "--value", "camserver"]
>>>>>>> Stashed changes


def test_status_all_services(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    result = svcmgr.handle_command("status", SERVICES)
    assert "camserver: active" in result
    assert "xspd: active" in result
    assert len(mock_systemctl.calls) == 2


# ---------------------------------------------------------------------------
<<<<<<< Updated upstream
=======
# Query command tests (substatus, unitfilestate, description, etc.)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "substatus", "unitfilestate", "startedtime", "description",
    "mainpid", "cputime", "numtasks", "uptime", "memoryusage", "log",
])
def test_query_missing_service_name(cmd):
    result = svcmgr.handle_command(cmd, SERVICES)
    assert "ERROR" in result
    assert "requires a service name" in result


@pytest.mark.parametrize("cmd", [
    "substatus", "unitfilestate", "startedtime", "description",
    "mainpid", "cputime", "numtasks", "uptime", "memoryusage", "log",
])
def test_query_unmanaged_service(cmd):
    result = svcmgr.handle_command("{} unknown_svc".format(cmd), SERVICES)
    assert "ERROR" in result
    assert "not a managed service" in result


def test_substatus(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "running\n", "")
    result = svcmgr.handle_command("substatus camserver", SERVICES)
    assert result == "Running"


def test_substatus_dead(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "dead\n", "")
    result = svcmgr.handle_command("substatus camserver", SERVICES)
    assert result == "Dead"


def test_unitfilestate(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "enabled\n", "")
    result = svcmgr.handle_command("unitfilestate camserver", SERVICES)
    assert result == "Enabled"


def test_unitfilestate_fallback_to_loadstate(mock_systemctl):
    """When UnitFileState is empty, falls back to LoadState."""
    call_count = [0]
    def fake_run(*args, **kwargs):
        mock_systemctl.calls.append((args, kwargs))
        call_count[0] += 1
        if call_count[0] == 1:
            return MockCompletedProcess(0, "\n", "")
        return MockCompletedProcess(0, "loaded\n", "")
    mock_systemctl.__class__.__call__ = lambda self, *a, **k: fake_run(*a, **k)
    result = svcmgr.handle_command("unitfilestate camserver", SERVICES)
    assert result == "Loaded"


def test_startedtime(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "Mon 2026-03-18 10:00:00 EDT\n", "")
    result = svcmgr.handle_command("startedtime camserver", SERVICES)
    assert result == "Mon 2026-03-18 10:00:00 EDT"


def test_startedtime_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "\n", "")
    result = svcmgr.handle_command("startedtime camserver", SERVICES)
    assert result == "n/a"


def test_description(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "Camera Server Daemon\n", "")
    result = svcmgr.handle_command("description camserver", SERVICES)
    assert result == "Camera Server Daemon"


def test_description_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "\n", "")
    result = svcmgr.handle_command("description camserver", SERVICES)
    assert result == "n/a"


def test_mainpid(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "12345\n", "")
    result = svcmgr.handle_command("mainpid camserver", SERVICES)
    assert result == "12345"


def test_mainpid_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "\n", "")
    result = svcmgr.handle_command("mainpid camserver", SERVICES)
    assert result == "0"


def test_cputime(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "5000000000\n", "")
    result = svcmgr.handle_command("cputime camserver", SERVICES)
    assert result == "5s"


def test_numtasks(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "4\n", "")
    result = svcmgr.handle_command("numtasks camserver", SERVICES)
    assert result == "4"


def test_numtasks_invalid(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "[not set]\n", "")
    result = svcmgr.handle_command("numtasks camserver", SERVICES)
    assert result == "0"


def test_memoryusage(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "104857600\n", "")
    result = svcmgr.handle_command("memoryusage camserver", SERVICES)
    assert "100.0MB" in result


def test_memoryusage_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "\n", "")
    result = svcmgr.handle_command("memoryusage camserver", SERVICES)
    assert result == "0B"


def test_log(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "line1\nline2\nline3\n", "")
    result = svcmgr.handle_command("log camserver", SERVICES)
    assert "line1" in result
    assert "line3" in result


# ---------------------------------------------------------------------------
# format_nanoseconds tests
# ---------------------------------------------------------------------------

def test_format_nanoseconds_seconds():
    assert svcmgr.format_nanoseconds("5000000000") == "5s"


def test_format_nanoseconds_minutes():
    assert svcmgr.format_nanoseconds("90000000000") == "1m 30s"


def test_format_nanoseconds_hours():
    assert svcmgr.format_nanoseconds("3661000000000") == "1h 1m 1s"


def test_format_nanoseconds_zero():
    assert svcmgr.format_nanoseconds("0") == "0s"


def test_format_nanoseconds_invalid():
    assert svcmgr.format_nanoseconds("not_a_number") == "0s"


def test_format_nanoseconds_empty():
    assert svcmgr.format_nanoseconds("") == "0s"


# ---------------------------------------------------------------------------
# format_bytes tests
# ---------------------------------------------------------------------------

def test_format_bytes_bytes():
    assert svcmgr.format_bytes("500") == "500B"


def test_format_bytes_kilobytes():
    assert svcmgr.format_bytes("2048") == "2.0KB"


def test_format_bytes_megabytes():
    result = svcmgr.format_bytes("104857600")
    assert "100.0MB" in result


def test_format_bytes_gigabytes():
    result = svcmgr.format_bytes("1073741824")
    assert "1.0GB" in result


def test_format_bytes_zero():
    assert svcmgr.format_bytes("0") == "0B"


def test_format_bytes_invalid():
    assert svcmgr.format_bytes("bad") == "0B"


def test_format_bytes_empty():
    assert svcmgr.format_bytes("") == "0B"


# ---------------------------------------------------------------------------
# get_systemd_property tests
# ---------------------------------------------------------------------------

def test_get_systemd_property(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "active\n", "")
    result = svcmgr.get_systemd_property("camserver", "ActiveState")
    assert result == "active"
    assert mock_systemctl.calls[0][0][0] == [
        "systemctl", "show", "-p", "ActiveState", "--value", "camserver"
    ]


def test_get_systemd_property_empty(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "\n", "")
    result = svcmgr.get_systemd_property("camserver", "ActiveState")
    assert result == ""


def test_get_systemd_property_exception(mock_systemctl):
    mock_systemctl.side_effect = OSError("fail")
    result = svcmgr.get_systemd_property("camserver", "ActiveState")
    assert result == ""


# ---------------------------------------------------------------------------
# get_journal_lines tests
# ---------------------------------------------------------------------------

def test_get_journal_lines(mock_systemctl):
    mock_systemctl.return_value = MockCompletedProcess(0, "log line 1\nlog line 2\n", "")
    result = svcmgr.get_journal_lines("camserver")
    assert "log line 1" in result
    assert "log line 2" in result


def test_get_journal_lines_exception(mock_systemctl):
    mock_systemctl.side_effect = OSError("fail")
    result = svcmgr.get_journal_lines("camserver")
    assert result == ""


# ---------------------------------------------------------------------------
# compute_uptime tests
# ---------------------------------------------------------------------------

def test_compute_uptime_empty():
    assert svcmgr.compute_uptime("") == "0s"


def test_compute_uptime_na():
    assert svcmgr.compute_uptime("n/a") == "0s"


# ---------------------------------------------------------------------------
>>>>>>> Stashed changes
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
