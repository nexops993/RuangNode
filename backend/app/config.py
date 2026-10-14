"""Konfigurasi RuangNode Dashboard (dibaca dari berkas env systemd)."""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.environ.get("DASH_ENV_FILE", "/etc/ruangnode-dashboard/env")

CFG = {"PORT": "8091", "DATA_DIR": "/data", "PASSWORD_HASH": "", "SESSION_SECRET": ""}


def load_env():
    cfg = dict(CFG)
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return cfg


CFG = load_env()

# Lokasi basis data SQLite (riwayat metrik). Utamakan kartu SD (/data),
# jatuh kembali ke folder aplikasi bila /data tidak ada.
def db_path():
    base = os.path.join(CFG.get("DATA_DIR", "/data"), "dashboard")
    if not os.path.isdir(CFG.get("DATA_DIR", "/data")):
        base = APP_DIR
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = APP_DIR
    return os.path.join(base, "ruangnode.db")


def frontend_dist():
    env = os.environ.get("FRONTEND_DIST")
    if env:
        return env
    return os.path.join(os.path.dirname(APP_DIR), "frontend", "dist")
