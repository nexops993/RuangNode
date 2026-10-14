"""Sampler status sistem + info service (port setia dari versi lama)."""
import os
import shutil
import subprocess
import threading
import time

from .config import CFG

CACHE = {"cpu_pct": 0.0, "temp_c": None, "net": {"iface": None, "rx_bps": 0, "tx_bps": 0}}
CACHE_LOCK = threading.Lock()


def read_cpu():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:]
    vals = [int(x) for x in parts[:8]]
    idle = vals[3] + vals[4]
    total = sum(vals)
    return idle, total


def read_temp():
    base = "/sys/class/thermal"
    try:
        for name in sorted(os.listdir(base)):
            if name.startswith("thermal_zone"):
                p = os.path.join(base, name, "temp")
                try:
                    with open(p) as f:
                        v = int(f.read().strip())
                    return round(v / 1000.0, 1) if v > 1000 else float(v)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def default_iface():
    # Kolom /proc/net/route: Iface, Destination, Gateway, Flags, RefCnt, Use, Metric, Mask
    # Rute default = Destination 00000000 dengan Gateway bukan 0; pilih metrik terkecil.
    best = None
    best_metric = None
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts[1] == "00000000" and parts[2] != "00000000":
                    metric = int(parts[6])
                    if best_metric is None or metric < best_metric:
                        best, best_metric = parts[0], metric
    except Exception:
        pass
    return best


def read_net(iface):
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" in line:
                    name, rest = line.split(":", 1)
                    if name.strip() == iface:
                        nums = rest.split()
                        return int(nums[0]), int(nums[8])
    except Exception:
        pass
    return 0, 0


def sampler():
    prev_idle, prev_total = read_cpu()
    iface = default_iface()
    prev_rx, prev_tx = read_net(iface) if iface else (0, 0)
    prev_t = time.time()
    while True:
        time.sleep(2)
        try:
            idle, total = read_cpu()
            di, dt = idle - prev_idle, total - prev_total
            pct = round(100.0 * (1 - di / dt), 1) if dt > 0 else 0.0
            prev_idle, prev_total = idle, total
            rx, tx = read_net(iface) if iface else (0, 0)
            now = time.time()
            span = now - prev_t
            prev_t = now
            with CACHE_LOCK:
                CACHE["cpu_pct"] = pct
                CACHE["temp_c"] = read_temp()
                CACHE["net"] = {
                    "iface": iface,
                    "rx_bps": int((rx - prev_rx) / span) if span > 0 else 0,
                    "tx_bps": int((tx - prev_tx) / span) if span > 0 else 0,
                }
            prev_rx, prev_tx = rx, tx
        except Exception:
            pass


def mem_info():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.split()[0]) * 1024
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    sw_total = info.get("SwapTotal", 0)
    sw_free = info.get("SwapFree", 0)
    return {
        "total": total, "used": total - avail, "available": avail,
        "swap_total": sw_total, "swap_used": sw_total - sw_free,
    }


def tailscale_ip():
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        ip = out.stdout.strip().split("\n")[0]
        return ip or None
    except Exception:
        return None


def lan_ip():
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        for tok in out.stdout.split():
            if tok and not tok.startswith("100."):
                return tok
    except Exception:
        pass
    return None


def system_status():
    with CACHE_LOCK:
        cache = dict(CACHE)
        cache["net"] = dict(CACHE["net"])
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    os_name = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    root = shutil.disk_usage("/")
    data_dir = CFG.get("DATA_DIR", "/data")
    try:
        data = shutil.disk_usage(data_dir)
        data_d = {"total": data.total, "used": data.used, "free": data.free, "path": data_dir}
    except Exception:
        data_d = None
    return {
        "hostname": os.uname().nodename,
        "os": os_name,
        "kernel": os.uname().release,
        "arch": os.uname().machine,
        "uptime_s": int(up),
        "load": list(os.getloadavg()),
        "cpu_pct": cache["cpu_pct"],
        "temp_c": cache["temp_c"],
        "mem": mem_info(),
        "disk_root": {"total": root.total, "used": root.used, "free": root.free, "path": "/"},
        "disk_data": data_d,
        "net": cache["net"],
        "tailscale_ip": tailscale_ip(),
        "lan_ip": lan_ip(),
    }


# ---------------- service ----------------

# service kritikal: hanya restart (menghentikan = memutus akses jarak jauh)
PROTECTED_RESTART_ONLY = {"tailscaled", "ssh"}
# service yang mengendalikan dashboard/tunnel itu sendiri: status saja
STATUS_ONLY = {"ruangnode-dashboard", "cloudflared"}
FULL_CONTROL = {"docker", "containerd"}
SERVICE_LIST = ["tailscaled", "ssh", "docker", "containerd", "cloudflared", "ruangnode-dashboard"]


def unit_exists(name):
    r = subprocess.run(["systemctl", "cat", name], capture_output=True, timeout=8)
    return r.returncode == 0


def service_status(name):
    r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=8)
    return r.stdout.strip() or "unknown"


def services_info():
    out = []
    for name in SERVICE_LIST:
        if not unit_exists(name):
            continue
        if name in PROTECTED_RESTART_ONLY:
            mode = "restart-only"
        elif name in STATUS_ONLY:
            mode = "status-only"
        elif name in FULL_CONTROL:
            mode = "full"
        else:
            mode = "status-only"
        out.append({"name": name, "status": service_status(name), "mode": mode})
    return out
