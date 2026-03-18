# svcmgr

A TCP socket server that exposes an ASCII command interface for managing systemd services.

## Prerequisites

- Python 3.6+
- systemd-based Linux system
- Root access (for installation and optionally service account setup)

## Installation

### 1. Create a service account (optional)

If you already have a non-root user account you'd like to run the service as,
skip this step and update the `User` and `Group` fields in the service file
accordingly. Otherwise, create a dedicated account:

```bash
sudo useradd -r -s /usr/sbin/nologin svcmgr
```

### 2. Install the script

```bash
sudo install -m 755 svcmgr.py /usr/local/bin/svcmgr.py
```

### 3. Configure the service file

Edit `svcmgr.service` to set the bind address, port, and the list of services to manage:

```ini
ExecStart=/usr/bin/python3 /usr/local/bin/svcmgr.py --interface 127.0.0.1 --port 9876 camserver xspd
```

If using an existing user account instead of `svcmgr`, update the `User` and `Group` fields as well.

### 4. Install and enable the service

```bash
sudo cp svcmgr.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now svcmgr
```

### 5. Grant systemctl permissions

Since the service does not run as root, the `svcmgr` user needs permission to
manage the target services. Create a polkit rule that restricts access to
specific service names (replace `camserver.service` and `xspd.service` with your
actual service names):

> **Note:** The `subject.user` value must match the account the svcmgr service
> runs as (i.e. the `User=` field in the service file).

```bash
sudo tee /etc/polkit-1/rules.d/50-svcmgr.rules << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "svcmgr" &&
        (action.lookup("unit") == "camserver.service" ||
         action.lookup("unit") == "xspd.service") &&
        (action.lookup("verb") == "start" ||
         action.lookup("verb") == "stop" ||
         action.lookup("verb") == "restart")) {
        return polkit.Result.YES;
    }
});
EOF
```

## Usage

### Connecting

Use any TCP client to connect. For example, with `nc`:

```bash
nc 127.0.0.1 9876
```

### Commands

| Command             | Description                          |
|---------------------|--------------------------------------|
| `status`            | Show status of all managed services  |
| `status <service>`  | Detailed status of one service       |
| `start <service>`   | Start a managed service              |
| `stop <service>`    | Stop a managed service               |
| `restart <service>` | Restart a managed service            |
| `list`              | List managed service names           |
| `help`              | Show available commands              |
| `quit`              | Close the connection                 |

### Example session

```
$ nc 127.0.0.1 9876
list
camserver
xspd

status
camserver: active
xspd: active

restart camserver
OK: restart camserver

quit
BYE
```

## Managing the service

```bash
# Check status
sudo systemctl status svcmgr

# View logs
sudo journalctl -u svcmgr -f

# Restart
sudo systemctl restart svcmgr

# Disable and stop
sudo systemctl disable --now svcmgr
```

## Uninstalling

```bash
sudo systemctl disable --now svcmgr
sudo rm /etc/systemd/system/svcmgr.service
sudo rm /usr/local/bin/svcmgr.py
sudo rm -f /etc/polkit-1/rules.d/50-svcmgr.rules
sudo rm -f /etc/sudoers.d/svcmgr
sudo userdel svcmgr
sudo systemctl daemon-reload
```
