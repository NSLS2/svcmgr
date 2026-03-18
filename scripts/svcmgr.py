#!/usr/bin/env python3
"""
svcmgr - A socket-based ASCII interface for managing systemd services.

Accepts a list of systemd service names and exposes a TCP socket server
that supports start, restart, stop, and status commands.

Protocol (newline-delimited ASCII):
    REQUEST:  <command> [service_name]
    RESPONSE: single or multi-line text, terminated by empty line

Commands:
    status              - Show status of all managed services
    status <service>    - Show status of a specific service
    start <service>     - Start a service
    stop <service>      - Stop a service
    restart <service>   - Restart a service
    list                - List all managed service names
    help                - Show available commands
    quit                - Close the connection
"""

import argparse
import logging
import signal
import socket
import subprocess
import sys
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("svcmgr")


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876

def run_systemctl(action: str, service: str) -> tuple[int, str]:
    """Run a systemctl command and return (returncode, combined output)."""
    try:
        result = subprocess.run(
            ["systemctl", action, service],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, f"Timeout running: systemctl {action} {service}"
    except Exception as e:
        return 1, str(e)


def get_service_status(service: str) -> str:
    """Return a short status string for a service."""
    rc, output = run_systemctl("is-active", service)
    state = output.splitlines()[0] if output else "unknown"
    return state


def handle_command(command_line: str, services: list[str]) -> str:
    """Parse and execute a single command. Returns the response string."""
    parts = command_line.strip().split(None, 1)
    if not parts:
        return "ERROR: empty command. Type 'help' for usage."

    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None

    if cmd == "help":
        return (
            "Available commands:\n"
            "  status [service]  - Show status (all or one)\n"
            "  start <service>   - Start a managed service\n"
            "  stop <service>    - Stop a managed service\n"
            "  restart <service> - Restart a managed service\n"
            "  list              - List managed services\n"
            "  help              - Show this help\n"
            "  quit              - Close connection"
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
        rc, output = run_systemctl("status", arg)
        return output if output else "(no output)"

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


def handle_client(conn: socket.socket, addr, services: list[str]) -> None:
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


def serve(host: str, port: int, services: list[str]) -> None:
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
    serve(args.interface, args.port, args.services)


if __name__ == "__main__":
    main()
