"""Penampil log sistem via journalctl (unit dibatasi whitelist)."""
import subprocess

LOG_UNITS = {"ruangnode-dashboard", "cloudflared", "tailscaled", "ssh", "docker", "containerd", "sistem"}


def system_logs(unit, lines):
    lines = max(20, min(400, lines))
    if unit == "sistem":
        cmd = ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"]
    else:
        cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return (r.stdout + r.stderr)[-12000:]
