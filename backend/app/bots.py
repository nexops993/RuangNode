"""Panel Bot ala Pterodactyl: tiap bot = satu container Docker dengan
runtime pilihan (Node.js / Python), folder kerja sendiri di
/data/bots/<slug>, batas RAM, variabel env, dan perintah start sendiri.

Metadata bot disimpan di tabel `bots` pada SQLite yang sama dengan
riwayat. Berkas bot murni di disk sehingga tetap bisa dijangkau juga
dari File Manager.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile

from .config import CFG, db_path

BOTS_DIR = os.path.join(CFG.get("DATA_DIR", "/data"), "bots")
WORKDIR = "/app"
MAX_EDIT_BYTES = 512_000

RUNTIMES = {
    "node22": {
        "label": "Node.js 22", "image": "node:22-alpine",
        "default_start": "node index.js",
        "install_cmd": "npm install", "install_marker": "package.json",
    },
    "node24": {
        "label": "Node.js 24", "image": "node:24-alpine",
        "default_start": "node index.js",
        "install_cmd": "npm install", "install_marker": "package.json",
    },
    "python311": {
        "label": "Python 3.11", "image": "python:3.11-slim",
        "default_start": "python bot.py",
        "install_cmd": "pip install -r requirements.txt", "install_marker": "requirements.txt",
    },
    "python312": {
        "label": "Python 3.12", "image": "python:3.12-slim",
        "default_start": "python bot.py",
        "install_cmd": "pip install -r requirements.txt", "install_marker": "requirements.txt",
    },
}

_db_lock = threading.Lock()
PROVISION = {}
PROVISION_LOCK = threading.Lock()
INSTALL_JOB = {}
INSTALL_LOCK = threading.Lock()


# ---------------- penyimpanan ----------------

def _conn():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(BOTS_DIR, exist_ok=True)
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bots ("
                " slug TEXT PRIMARY KEY, name TEXT NOT NULL, runtime TEXT NOT NULL,"
                " start_cmd TEXT NOT NULL, mem_limit_mb INTEGER NOT NULL DEFAULT 512,"
                " auto_restart INTEGER NOT NULL DEFAULT 1, env_json TEXT NOT NULL DEFAULT '{}',"
                " created_ts INTEGER NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()


def _row_to_bot(r):
    return {
        "slug": r["slug"], "name": r["name"], "runtime": r["runtime"],
        "start_cmd": r["start_cmd"], "mem_limit_mb": r["mem_limit_mb"],
        "auto_restart": bool(r["auto_restart"]),
        "env": json.loads(r["env_json"] or "{}"),
        "created_ts": r["created_ts"],
        "dir": os.path.join(BOTS_DIR, r["slug"]),
    }


def list_bots():
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM bots ORDER BY created_ts").fetchall()
        finally:
            conn.close()
    return [_row_to_bot(r) for r in rows]


def get_bot(slug):
    with _db_lock:
        conn = _conn()
        try:
            r = conn.execute("SELECT * FROM bots WHERE slug = ?", (slug,)).fetchone()
        finally:
            conn.close()
    return _row_to_bot(r) if r else None


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40].strip("-")
    return s or "bot"


def unique_slug(name):
    base = slugify(name)
    slug = base
    n = 2
    while get_bot(slug) is not None or os.path.exists(os.path.join(BOTS_DIR, slug)):
        slug = "%s-%d" % (base, n)
        n += 1
    return slug


# ---------------- docker ----------------

def docker_ok():
    return shutil.which("docker") is not None


def cname(slug):
    return "rn-bot-" + slug


def container_info():
    out = {}
    if not docker_ok():
        return out
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
                           capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                out[parts[0]] = {"status_text": parts[1], "state": parts[2]}
        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"],
                           capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] in out:
                out[parts[0]]["mem"] = parts[1].split("/")[0].strip()
                out[parts[0]]["cpu"] = parts[2]
    except Exception:
        pass
    return out


def _create_container(bot):
    rt = RUNTIMES[bot["runtime"]]
    args = ["docker", "create", "--name", cname(bot["slug"]),
            "--restart", "unless-stopped" if bot["auto_restart"] else "no",
            "--memory", "%dm" % int(bot["mem_limit_mb"]),
            "-v", "%s:%s" % (bot["dir"], WORKDIR), "-w", WORKDIR]
    for k, v in (bot.get("env") or {}).items():
        args += ["-e", "%s=%s" % (k, v)]
    args += [rt["image"], "sh", "-c", bot["start_cmd"]]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stderr or "")[-300:]


def _provision_worker(slug):
    def set_state(state, detail=""):
        with PROVISION_LOCK:
            PROVISION[slug] = {"state": state, "detail": detail, "ts": int(time.time())}
    bot = get_bot(slug)
    if not bot:
        return
    try:
        set_state("menarik image runtime (bisa beberapa menit)")
        rt = RUNTIMES[bot["runtime"]]
        r = subprocess.run(["docker", "pull", rt["image"]], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            set_state("gagal", (r.stderr or "docker pull gagal")[-300:])
            return
        set_state("membuat container")
        okk, msg = _create_container(bot)
        if not okk:
            set_state("gagal", msg)
            return
        set_state("selesai")
    except Exception as ex:
        set_state("gagal", str(ex)[-300:])


def create_bot(name, runtime, start_cmd, mem_limit_mb, auto_restart, env):
    if runtime not in RUNTIMES:
        return None, "runtime tidak dikenal"
    if not docker_ok():
        return None, "docker tidak tersedia"
    slug = unique_slug(name)
    bot_dir = os.path.join(BOTS_DIR, slug)
    os.makedirs(bot_dir, exist_ok=True)
    try:
        os.chmod(bot_dir, 0o777)
    except Exception:
        pass
    bot = {
        "slug": slug, "name": str(name)[:60] or slug, "runtime": runtime,
        "start_cmd": (start_cmd or RUNTIMES[runtime]["default_start"])[:300],
        "mem_limit_mb": max(64, min(2048, int(mem_limit_mb or 512))),
        "auto_restart": bool(auto_restart),
        "env": env or {}, "created_ts": int(time.time()), "dir": bot_dir,
    }
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO bots (slug, name, runtime, start_cmd, mem_limit_mb, auto_restart, env_json, created_ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (bot["slug"], bot["name"], bot["runtime"], bot["start_cmd"], bot["mem_limit_mb"],
                 1 if bot["auto_restart"] else 0, json.dumps(bot["env"]), bot["created_ts"]))
            conn.commit()
        finally:
            conn.close()
    threading.Thread(target=_provision_worker, args=(slug,), daemon=True).start()
    return bot, None


def bots_overview():
    conts = container_info()
    out = []
    for bot in list_bots():
        c = conts.get(cname(bot["slug"]))
        with PROVISION_LOCK:
            prov = dict(PROVISION.get(bot["slug"], {}))
        entry = dict(bot)
        entry.update({
            "runtime_label": RUNTIMES[bot["runtime"]]["label"],
            "image": RUNTIMES[bot["runtime"]]["image"],
            "installed": c is not None,
            "state": c["state"] if c else None,
            "status_text": c["status_text"] if c else None,
            "mem_usage": c.get("mem") if c else None,
            "cpu_usage": c.get("cpu") if c else None,
            "provision": prov or None,
        })
        out.append(entry)
    return {
        "docker": docker_ok(),
        "runtimes": [{"id": k, "label": v["label"], "image": v["image"],
                      "default_start": v["default_start"]} for k, v in RUNTIMES.items()],
        "bots": out,
    }


def bot_action(slug, action, wipe=False):
    bot = get_bot(slug)
    if not bot:
        return False, "bot tidak ditemukan"
    name = cname(slug)
    if action in ("start", "stop", "restart"):
        r = subprocess.run(["docker", action, name], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, (r.stderr or "gagal")[-200:]
        return True, "ok"
    if action == "delete":
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)
        with _db_lock:
            conn = _conn()
            try:
                conn.execute("DELETE FROM bots WHERE slug = ?", (slug,))
                conn.commit()
            finally:
                conn.close()
        with PROVISION_LOCK:
            PROVISION.pop(slug, None)
        if wipe:
            shutil.rmtree(bot["dir"], ignore_errors=True)
        return True, "ok"
    return False, "aksi tidak dikenal"


def update_config(slug, start_cmd=None, mem_limit_mb=None, auto_restart=None, env=None):
    bot = get_bot(slug)
    if not bot:
        return False, "bot tidak ditemukan"
    if start_cmd is not None:
        bot["start_cmd"] = str(start_cmd)[:300] or bot["start_cmd"]
    if mem_limit_mb is not None:
        bot["mem_limit_mb"] = max(64, min(2048, int(mem_limit_mb)))
    if auto_restart is not None:
        bot["auto_restart"] = bool(auto_restart)
    if env is not None:
        bot["env"] = {str(k)[:100]: str(v)[:1000] for k, v in dict(env).items()}
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE bots SET start_cmd = ?, mem_limit_mb = ?, auto_restart = ?, env_json = ? WHERE slug = ?",
                (bot["start_cmd"], bot["mem_limit_mb"], 1 if bot["auto_restart"] else 0,
                 json.dumps(bot["env"]), slug))
            conn.commit()
        finally:
            conn.close()
    # container dibuat ulang (keadaan berhenti) agar konfigurasi berlaku
    conts = container_info()
    if cname(slug) in conts:
        subprocess.run(["docker", "rm", "-f", cname(slug)], capture_output=True, text=True, timeout=60)
        okk, msg = _create_container(bot)
        if not okk:
            return False, "konfigurasi tersimpan tapi container gagal dibuat ulang: " + msg
    return True, "ok"


def bot_logs(slug, tail=200):
    if not get_bot(slug):
        return None
    r = subprocess.run(["docker", "logs", "--tail", str(tail), "--timestamps", cname(slug)],
                       capture_output=True, text=True, timeout=20)
    return (r.stdout + r.stderr)[-12000:]


def bot_exec(slug, cmd):
    bot = get_bot(slug)
    if not bot:
        return False, "bot tidak ditemukan"
    conts = container_info()
    info = conts.get(cname(slug))
    if not info or info["state"] != "running":
        return False, "bot tidak sedang berjalan — nyalakan dulu untuk menjalankan perintah"
    try:
        r = subprocess.run(["docker", "exec", cname(slug), "sh", "-c", str(cmd)[:500]],
                           capture_output=True, text=True, timeout=30)
        return True, (r.stdout + r.stderr)[-8000:]
    except subprocess.TimeoutExpired:
        return False, "perintah melewati batas 30 detik"


# ---------------- install dependensi ----------------

def _install_worker(slug):
    def set_state(state, log=""):
        with INSTALL_LOCK:
            INSTALL_JOB[slug] = {"state": state, "log": log[-8000:], "ts": int(time.time())}
    bot = get_bot(slug)
    if not bot:
        return
    rt = RUNTIMES[bot["runtime"]]
    marker = os.path.join(bot["dir"], rt["install_marker"])
    if not os.path.exists(marker):
        set_state("gagal", "Berkas %s tidak ditemukan di folder bot — unggah dulu kode botnya." % rt["install_marker"])
        return
    set_state("berjalan", "Menjalankan: %s\n" % rt["install_cmd"])
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--memory", "768m",
             "-v", "%s:%s" % (bot["dir"], WORKDIR), "-w", WORKDIR,
             rt["image"], "sh", "-c", rt["install_cmd"]],
            capture_output=True, text=True, timeout=1200)
        out = (r.stdout + r.stderr)[-8000:]
        if r.returncode == 0:
            set_state("selesai", out + "\n[install selesai]")
        else:
            set_state("gagal", out + "\n[install gagal, kode %d]" % r.returncode)
    except subprocess.TimeoutExpired:
        set_state("gagal", "Install melewati batas 20 menit.")
    except Exception as ex:
        set_state("gagal", str(ex)[-500:])


def start_install_deps(slug):
    if not get_bot(slug):
        return False
    with INSTALL_LOCK:
        cur = INSTALL_JOB.get(slug, {})
        if cur.get("state") == "berjalan":
            return False
    threading.Thread(target=_install_worker, args=(slug,), daemon=True).start()
    return True


def install_status(slug):
    with INSTALL_LOCK:
        return dict(INSTALL_JOB.get(slug, {})) or None


# ---------------- editor berkas ----------------

def _bot_file(bot, rel):
    base = os.path.realpath(bot["dir"])
    p = os.path.realpath(os.path.join(base, (rel or "").lstrip("/")))
    if p != base and not p.startswith(base + "/"):
        return None
    return p


def read_bot_file(slug, rel):
    bot = get_bot(slug)
    if not bot:
        return None, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None or not os.path.isfile(p):
        return None, "file tidak ditemukan"
    if os.path.getsize(p) > MAX_EDIT_BYTES:
        return None, "file terlalu besar untuk editor (maks 512 KB)"
    with open(p, "rb") as f:
        raw = f.read()
    if b"\x00" in raw[:8192]:
        return None, "file biner tidak bisa diedit di sini"
    return {"path": rel, "content": raw.decode("utf-8", "replace")}, None


def save_bot_file(slug, rel, content):
    bot = get_bot(slug)
    if not bot:
        return False, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None:
        return False, "jalur tidak diizinkan"
    data = str(content).encode("utf-8")
    if len(data) > MAX_EDIT_BYTES:
        return False, "isi melewati batas 512 KB"
    parent = os.path.dirname(p)
    if not os.path.isdir(parent):
        return False, "folder tujuan tidak ada"
    with open(p, "wb") as f:
        f.write(data)
    return True, "ok"


def extract_zip(slug, rel):
    bot = get_bot(slug)
    if not bot:
        return False, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None or not os.path.isfile(p):
        return False, "file zip tidak ditemukan"
    base = os.path.realpath(bot["dir"])
    count = 0
    total = 0
    try:
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                total += info.file_size
                if total > 200 * 1024 * 1024:
                    return False, "isi zip melewati batas 200 MB"
                dest = os.path.realpath(os.path.join(base, info.filename))
                if not dest.startswith(base + "/"):
                    return False, "zip berisi jalur tidak aman: " + info.filename
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
    except zipfile.BadZipFile:
        return False, "file bukan zip yang valid"
    return True, "%d file diekstrak" % count
