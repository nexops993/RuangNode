#!/usr/bin/env python3
"""RuangNode Connector Agent — Python murni (stdlib), tanpa dependensi.

Berjalan sebagai service systemd di mesin yang dikelola. Agent
terhubung KELUAR ke dashboard (HTTPS): melapor statistik berkala dan
mengambil perintah dari antrean dashboard (poll), menjalankannya,
lalu mengirim hasil kembali. Tidak ada port masuk yang dibuka.

Konfigurasi: /etc/ruangnode-connector/config.json
  {"url": "https://api.ruangnode.me", "token": "<token node>"}
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

AGENT_VERSION = "1.0"
CONFIG_PATH = os.environ.get("AGENT_CONFIG", "/etc/ruangnode-connector/config.json")
REPORT_EVERY = 10
POLL_EVERY = 2
MAX_RUN_OUTPUT = 200_000

CFG = {}
try:
    with open(CONFIG_PATH) as f:
        CFG = json.load(f)
except Exception as ex:
    print("gagal membaca konfigurasi %s: %s" % (CONFIG_PATH, ex), file=sys.stderr)
    sys.exit(1)

BASE = str(CFG.get("url") or "").rstrip("/")
TOKEN = str(CFG.get("token") or "")
BOTS_DIR = str(CFG.get("bots_dir") or ("/data/bots" if os.path.isdir("/data") else "/opt/ruangnode/bots"))


def http_post(path, body, timeout=20):
    req = urllib.request.Request(
        BASE + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
                 # UA bawaan urllib (Python-urllib) diblokir Cloudflare (403) —
                 # agent wajib memperkenalkan diri dengan UA sendiri.
                 "User-Agent": "RuangNode-Agent/" + AGENT_VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------- statistik (meniru bentuk status dashboard) ----------------

_prev = {"idle": 0, "total": 0, "rx": 0, "tx": 0, "t": 0.0, "iface": None}


def read_cpu_raw():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:]
    vals = [int(x) for x in parts[:8]]
    return vals[3] + vals[4], sum(vals)


def read_temp():
    base = "/sys/class/thermal"
    try:
        for name in sorted(os.listdir(base)):
            if name.startswith("thermal_zone"):
                try:
                    with open(os.path.join(base, name, "temp")) as f:
                        v = int(f.read().strip())
                    return round(v / 1000.0, 1) if v > 1000 else float(v)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def default_iface():
    best, best_metric = None, None
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


def mem_info():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.split()[0]) * 1024
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    return {"total": total, "used": total - avail, "available": avail,
            "swap_total": info.get("SwapTotal", 0),
            "swap_used": info.get("SwapTotal", 0) - info.get("SwapFree", 0)}


def _run_text(args, timeout=5):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except Exception:
        return ""


PROTECTED = {"tailscaled", "ssh"}
STATUS_ONLY = {"cloudflared", "ruangnode-agent", "ruangnode-dashboard"}
FULL = {"docker", "containerd"}
CANDIDATES = ["tailscaled", "ssh", "docker", "containerd", "cloudflared", "ruangnode-agent", "ruangnode-dashboard"]


def services_info():
    out = []
    for name in CANDIDATES:
        r = subprocess.run(["systemctl", "cat", name], capture_output=True, timeout=8)
        if r.returncode != 0:
            continue
        status = _run_text(["systemctl", "is-active", name], timeout=8) or "unknown"
        mode = ("restart-only" if name in PROTECTED else
                "full" if name in FULL else "status-only")
        out.append({"name": name, "status": status, "mode": mode})
    return out


def gather_status():
    now = time.time()
    idle, total = read_cpu_raw()
    iface = default_iface()
    rx, tx = read_net(iface) if iface else (0, 0)
    cpu_pct = 0.0
    rx_bps = tx_bps = 0
    if _prev["t"]:
        di, dt = idle - _prev["idle"], total - _prev["total"]
        cpu_pct = round(100.0 * (1 - di / dt), 1) if dt > 0 else 0.0
        span = now - _prev["t"]
        if span > 0:
            rx_bps = int((rx - _prev["rx"]) / span)
            tx_bps = int((tx - _prev["tx"]) / span)
    _prev.update({"idle": idle, "total": total, "rx": rx, "tx": tx, "t": now, "iface": iface})

    os_name = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    root = shutil.disk_usage("/")
    try:
        os.makedirs(BOTS_DIR, exist_ok=True)
        bd = shutil.disk_usage(BOTS_DIR)
        disk_data = {"total": bd.total, "used": bd.used, "free": bd.free, "path": BOTS_DIR}
    except Exception:
        disk_data = None
    ts_ip = _run_text(["tailscale", "ip", "-4"]).split("\n")[0] or None
    lan = None
    for tok in _run_text(["hostname", "-I"]).split():
        if tok and not tok.startswith("100."):
            lan = tok
            break
    return {
        "hostname": os.uname().nodename,
        "os": os_name,
        "kernel": os.uname().release,
        "arch": os.uname().machine,
        "uptime_s": int(up),
        "load": list(os.getloadavg()),
        "cpu_pct": cpu_pct,
        "temp_c": read_temp(),
        "mem": mem_info(),
        "disk_root": {"total": root.total, "used": root.used, "free": root.free, "path": "/"},
        "disk_data": disk_data,
        "net": {"iface": iface, "rx_bps": rx_bps, "tx_bps": tx_bps},
        "tailscale_ip": ts_ip,
        "lan_ip": lan,
        "services": services_info(),
        "docker": shutil.which("docker") is not None,
        "bots_dir": BOTS_DIR,
        "agent_version": AGENT_VERSION,
    }


# ---------------- eksekusi perintah ----------------

def cmd_run(p):
    timeout = max(1, min(1800, int(p.get("timeout") or 30)))
    try:
        r = subprocess.run(["/bin/sh", "-c", str(p.get("cmd") or "")],
                           capture_output=True, text=True, timeout=timeout)
        return {"code": r.returncode, "out": (r.stdout + r.stderr)[-MAX_RUN_OUTPUT:]}
    except subprocess.TimeoutExpired as ex:
        out = ""
        if ex.stdout:
            out += ex.stdout.decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else ex.stdout
        if ex.stderr:
            out += ex.stderr.decode("utf-8", "replace") if isinstance(ex.stderr, bytes) else ex.stderr
        return {"code": 124, "out": (out + "\n[melewati batas %d detik]" % timeout)[-MAX_RUN_OUTPUT:]}


def cmd_run_detached(p):
    subprocess.Popen(["/bin/sh", "-c", str(p.get("cmd") or "")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return {"started": True}


def _norm(path):
    p = str(path or "/")
    if not p.startswith("/"):
        p = "/" + p
    return os.path.realpath(p)


def cmd_fs_list(p):
    target = _norm(p.get("path"))
    items = []
    with os.scandir(target) as it:
        for e in it:
            try:
                st = e.stat()
                items.append({"name": e.name, "dir": e.is_dir(),
                              "size": st.st_size if not e.is_dir() else None,
                              "mtime": int(st.st_mtime)})
            except Exception:
                continue
    items.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return {"path": target, "items": items}


def cmd_fs_stat(p):
    target = _norm(p.get("path"))
    if not os.path.exists(target):
        return {"exists": False, "is_dir": False, "is_file": False, "size": None}
    return {"exists": True, "is_dir": os.path.isdir(target),
            "is_file": os.path.isfile(target),
            "size": os.path.getsize(target) if os.path.isfile(target) else None}


def cmd_fs_read(p):
    target = _norm(p.get("path"))
    offset = max(0, int(p.get("offset") or 0))
    length = max(1, min(1048576, int(p.get("length") or 262144)))
    size = os.path.getsize(target)
    with open(target, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    return {"data_b64": base64.b64encode(data).decode(),
            "size": size, "eof": offset + len(data) >= size, "read": len(data)}


def cmd_fs_write(p):
    target = _norm(p.get("path"))
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    data = base64.b64decode(p.get("data_b64") or "")
    mode = "ab" if p.get("append") else "wb"
    with open(target, mode) as f:
        f.write(data)
    return {"written": len(data)}


def cmd_fs_extract_zip(p):
    src = _norm(p.get("path"))
    base = _norm(p.get("dest"))
    count, total = 0, 0
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            total += info.file_size
            if total > 200 * 1024 * 1024:
                raise ValueError("isi zip melewati batas 200 MB")
            dest = os.path.realpath(os.path.join(base, info.filename))
            if not dest.startswith(base + "/"):
                raise ValueError("zip berisi jalur tidak aman: " + info.filename)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as s, open(dest, "wb") as out:
                shutil.copyfileobj(s, out)
            count += 1
    return {"count": count}


HANDLERS = {
    "run": cmd_run,
    "run_detached": cmd_run_detached,
    "fs_list": cmd_fs_list,
    "fs_stat": cmd_fs_stat,
    "fs_read": cmd_fs_read,
    "fs_write": cmd_fs_write,
    "fs_extract_zip": cmd_fs_extract_zip,
}


def execute(cmd):
    handler = HANDLERS.get(cmd.get("type"))
    if not handler:
        return False, None, "tipe perintah tidak dikenal: %s" % cmd.get("type")
    try:
        return True, handler(cmd.get("payload") or {}), None
    except Exception as ex:
        return False, None, str(ex)[:500]


def main():
    print("ruangnode-agent %s -> %s (bots: %s)" % (AGENT_VERSION, BASE, BOTS_DIR))
    last_report = 0.0
    while True:
        try:
            now = time.time()
            if now - last_report >= REPORT_EVERY:
                http_post("/api/agent/report", gather_status(), timeout=25)
                last_report = now
            res = http_post("/api/agent/poll", {}, timeout=25)
            for cmd in (res.get("data") or {}).get("commands") or []:
                ok, data, error = execute(cmd)
                try:
                    http_post("/api/agent/result",
                              {"id": cmd.get("id"), "ok": ok, "data": data, "error": error},
                              timeout=25)
                except Exception:
                    pass
        except Exception as ex:
            print("koneksi: %s" % ex, file=sys.stderr)
        time.sleep(POLL_EVERY)


if __name__ == "__main__":
    main()
