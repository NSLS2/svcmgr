#!/usr/bin/env python3
"""
svcmgr - A socket-based ASCII interface for managing systemd services.

Accepts a list of systemd service names and exposes a TCP socket server
that supports start, restart, stop, and status/property query commands.

Protocol (newline-delimited ASCII):
    REQUEST:  <command> [service_name]
    RESPONSE: single or multi-line text, terminated by empty line

Commands:
    status              - Show status of all managed services
    status <svc>        - Active state (Active, Inactive, etc.)
    substatus <svc>     - Sub-state (Running, Exited, etc.)
    unitfilestate <svc> - Unit file state (Enabled, Disabled, etc.)
    startedtime <svc>   - Last start timestamp
    description <svc>   - Service description
    mainpid <svc>       - Main PID
    cputime <svc>       - CPU time used
    numtasks <svc>      - Number of tasks
    uptime <svc>        - Uptime since last start
    memoryusage <svc>   - Memory usage
    log <svc>           - Recent journal log lines
    start <svc>         - Start a service
    stop <svc>          - Stop a service
    restart <svc>       - Restart a service
    list                - List all managed service names
    help                - Show available commands
    quit                - Close the connection
"""

import argparse
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
from typing import List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("svcmgr")


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876

def run_systemctl(action: str, service: str) -> Tuple[int, str]:
    """Run a systemctl command and return (returncode, combined output)."""
    try:
        result = subprocess.run(
            ["systemctl", action, service],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, f"Timeout running: systemctl {action} {service}"
    except Exception as e:
        return 1, str(e)


def get_systemd_property(service: str, prop: str) -> str:
    """Get a single property from systemctl show."""
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", prop, "--value", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_journal_lines(service: str, num_lines: int = 10) -> str:
    """Get recent journal log lines for a service."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", str(num_lines), "--no-pager"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def format_nanoseconds(ns_str: str) -> str:
    """Format a nanosecond value into a human-readable time string."""
    try:
        ns = int(ns_str)
    except (ValueError, TypeError):
        return "0s"
    seconds = ns // 1_000_000_000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m {secs}s"


def format_bytes(bytes_str: str) -> str:
    """Format a byte count into a human-readable string."""
    try:
        b = int(bytes_str)
    except (ValueError, TypeError):
        return "0B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b}{unit}" if unit == "B" else f"{b:.1f}{unit}"
            break
        b /= 1024
    return f"{b:.1f}PB"


def compute_uptime(timestamp_str: str) -> str:
    """Compute uptime from an ActiveEnterTimestamp string."""
    if not timestamp_str or timestamp_str == "n/a":
        return "0s"
    try:
        from datetime import datetime
        # systemd timestamps look like: "Mon 2026-03-18 10:00:00 EDT"
        # Use systemctl's monotonic approach instead
        result = subprocess.run(
            ["systemctl", "show", "-p", "ActiveEnterTimestampMonotonic", "--value"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5,
        )
        # Fallback: parse the human-readable timestamp
        import time as _time
        # Try parsing common systemd timestamp formats
        for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %Z"):
            try:
                dt = datetime.strptime(timestamp_str, fmt)
                delta = datetime.now() - dt
                total_secs = int(delta.total_seconds())
                if total_secs < 0:
                    return "0s"
                return format_nanoseconds(str(total_secs * 1_000_000_000))
            except ValueError:
                continue
        return timestamp_str
    except Exception:
        return timestamp_str


def get_service_status(service: str) -> str:
    """Return a short status string for a service."""
    rc, output = run_systemctl("is-active", service)
    state = output.splitlines()[0] if output else "unknown"
    return state


def handle_command(command_line: str, services: List[str]) -> str:
    """Parse and execute a single command. Returns the response string."""
    parts = command_line.strip().split(None, 1)
    if not parts:
        return "ERROR: empty command. Type 'help' for usage."

    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None

    if cmd == "help":
        return (
            "Available commands:\n"
            "  status [svc]           - Active state (all or one)\n"
            "  substatus <svc>        - Sub-state (running, exited, etc.)\n"
            "  unitfilestate <svc>    - Unit file state\n"
            "  startedtime <svc>      - Last start timestamp\n"
            "  description <svc>      - Service description\n"
            "  mainpid <svc>          - Main PID\n"
            "  cputime <svc>          - CPU time used\n"
            "  numtasks <svc>         - Number of tasks\n"
            "  uptime <svc>           - Uptime since last start\n"
            "  memoryusage <svc>      - Memory usage\n"
            "  log <svc>              - Recent log lines\n"
            "  start <svc>            - Start a managed service\n"
            "  stop <svc>             - Stop a managed service\n"
            "  restart <svc>          - Restart a managed service\n"
            "  list                   - List managed services\n"
            "  help                   - Show this help\n"
            "  quit                   - Close connection"
        )

    if cmd == "list":
        return "\n".join(services)

    if cmd == "status":
        if arg is None:
            lines = []
            for svc in services:
                state = get_service_status(svc)
                lines.append(f"{svc}: {state}")
            return "\n".join(lines)
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "ActiveState")
        return raw.capitalize() if raw else "unknown"

    if cmd == "substatus":
        if arg is None:
            return "ERROR: 'substatus' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "SubState")
        return raw.capitalize() if raw else "unknown"

    if cmd == "unitfilestate":
        if arg is None:
            return "ERROR: 'unitfilestate' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "UnitFileState")
        if not raw:
            raw = get_systemd_property(arg, "LoadState")
        return raw.capitalize() if raw else "unknown"

    if cmd == "startedtime":
        if arg is None:
            return "ERROR: 'startedtime' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "ExecMainStartTimestamp")
        return raw if raw else "n/a"

    if cmd == "description":
        if arg is None:
            return "ERROR: 'description' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "Description")
        return raw if raw else "n/a"

    if cmd == "mainpid":
        if arg is None:
            return "ERROR: 'mainpid' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "MainPID")
        return raw if raw else "0"

    if cmd == "cputime":
        if arg is None:
            return "ERROR: 'cputime' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "CPUUsageNSec")
        return format_nanoseconds(raw)

    if cmd == "numtasks":
        if arg is None:
            return "ERROR: 'numtasks' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "TasksCurrent")
        try:
            return str(int(raw))
        except (ValueError, TypeError):
            return "0"

    if cmd == "uptime":
        if arg is None:
            return "ERROR: 'uptime' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "ActiveEnterTimestamp")
        return compute_uptime(raw)

    if cmd == "memoryusage":
        if arg is None:
            return "ERROR: 'memoryusage' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        raw = get_systemd_property(arg, "MemoryCurrent")
        return format_bytes(raw)

    if cmd == "log":
        if arg is None:
            return "ERROR: 'log' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        return get_journal_lines(arg)

    if cmd in ("start", "stop", "restart"):
        if arg is None:
            return f"ERROR: '{cmd}' requires a service name."
        if arg not in services:
            return f"ERROR: '{arg}' is not a managed service."
        rc, output = run_systemctl(cmd, arg)
        if rc == 0:
            return f"OK: {cmd} {arg}"
        return f"FAIL: {cmd} {arg}\n{output}"

    return f"ERROR: unknown command '{cmd}'. Type 'help' for usage."


def handle_client(conn: socket.socket, addr: object, services: List[str]) -> None:
    """Handle a single client connection."""
    logger.info("Client connected from %s", addr)
    with conn:
        buf = b""
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                command_line = line.decode("utf-8", errors="replace").strip()
                if command_line.lower() == "quit":
                    conn.sendall(b"BYE\n\n")
                    logger.info("Client %s disconnected (quit)", addr)
                    return
                logger.debug("Command from %s: %s", addr, command_line)
                response = handle_command(command_line, services)
                # Send response followed by a blank line as terminator
                conn.sendall((response + "\n\n").encode("utf-8"))
    logger.info("Client %s disconnected", addr)


def serve(host: str, port: int, services: List[str]) -> None:
    """Run the TCP socket server."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)

    # Graceful shutdown on SIGINT / SIGTERM
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("svcmgr listening on %s:%d", host, port)
    logger.info("Managing services: %s", ", ".join(services))

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr, services),
                daemon=True,
            )
            t.start()
    except OSError:
        pass
    finally:
        server.close()


def main():
    parser = argparse.ArgumentParser(
        description="Manage systemd services over a TCP socket interface."
    )
    parser.add_argument(
        "services",
        nargs="+",
        help="Systemd service names to manage (e.g. nginx sshd docker).",
    )
    parser.add_argument(
        "-i", "--interface",
        default=DEFAULT_HOST,
        help=f"IP address to bind to (default: {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to listen on (default: {DEFAULT_PORT}).",
    )
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Refusing to run as root. Use a dedicated service account.")
    serve(args.interface, args.port, args.services)


if __name__ == "__main__":
    main()
