"""Panel Bot ala Pterodactyl — multi-node.

Tiap bot = satu container Docker dengan runtime pilihan (Node.js /
Python), folder kerja sendiri, batas RAM, variabel env, dan perintah
start sendiri. Metadata bot disimpan di tabel `bots` pada SQLite
dashboard (kolom node_id membedakan node lokal vs node agent).

Di node lokal semua dikerjakan langsung; di node agent, perintah
docker dijalankan lewat RPC agent (nodes.call) dan berkas bot diakses
lewat perintah fs_* agent. Tampilan & kontrak API tetap sama.
"""
import base64
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile

from . import nodes
from .config import CFG, db_path

BOTS_DIR = os.path.join(CFG.get("DATA_DIR", "/data"), "bots")
WORKDIR = "/app"
MAX_EDIT_BYTES = 512_000
REMOTE_BOTS_DEFAULT = "/opt/ruangnode/bots"

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


def _key(node_id, slug):
    return node_id + ":" + slug


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
                " created_ts INTEGER NOT NULL,"
                " node_id TEXT NOT NULL DEFAULT 'local', dir TEXT)")
            cols = [r[1] for r in conn.execute("PRAGMA table_info(bots)").fetchall()]
            if "node_id" not in cols:
                conn.execute("ALTER TABLE bots ADD COLUMN node_id TEXT NOT NULL DEFAULT 'local'")
            if "dir" not in cols:
                conn.execute("ALTER TABLE bots ADD COLUMN dir TEXT")
            conn.execute(
                "UPDATE bots SET dir = ? || '/' || slug WHERE dir IS NULL OR dir = ''",
                (BOTS_DIR,))
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
        "node_id": r["node_id"] or "local",
        "dir": r["dir"] or os.path.join(BOTS_DIR, r["slug"]),
    }


def list_bots(node_id="local"):
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM bots WHERE node_id = ? ORDER BY created_ts", (node_id,)).fetchall()
        finally:
            conn.close()
    return [_row_to_bot(r) for r in rows]


def get_bot(node_id, slug):
    with _db_lock:
        conn = _conn()
        try:
            r = conn.execute(
                "SELECT * FROM bots WHERE node_id = ? AND slug = ?", (node_id, slug)).fetchone()
        finally:
            conn.close()
    return _row_to_bot(r) if r else None


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40].strip("-")
    return s or "bot"


def unique_slug(node_id, name):
    base = slugify(name)
    slug = base
    n = 2
    while get_bot(node_id, slug) is not None or (
            node_id == "local" and os.path.exists(os.path.join(BOTS_DIR, slug))):
        slug = "%s-%d" % (base, n)
        n += 1
    return slug


# ---------------- jembatan eksekusi (lokal vs agent) ----------------

def _sh(node_id, cmd, timeout=30):
    """Jalankan perintah shell. -> (transport_ok, rc, teks gabungan)"""
    if node_id == "local":
        try:
            r = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=timeout)
            return True, r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired as ex:
            out = ""
            if ex.stdout:
                out += ex.stdout.decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else ex.stdout
            if ex.stderr:
                out += ex.stderr.decode("utf-8", "replace") if isinstance(ex.stderr, bytes) else ex.stderr
            return True, 124, out + "\n[melewati batas %d detik]" % timeout
        except Exception as ex:
            return False, 1, str(ex)
    ok, data, error = nodes.call(node_id, "run", {"cmd": cmd, "timeout": timeout}, timeout=timeout + 20)
    if not ok:
        return False, 1, error or "node tidak menjawab"
    return True, int(data.get("code", 1)), str(data.get("out") or "")


def _fs_exists(node_id, path):
    if node_id == "local":
        return os.path.exists(path)
    ok, data, _ = nodes.call(node_id, "fs_stat", {"path": path}, timeout=20)
    return bool(ok and data and data.get("exists"))


def _fs_read_bytes(node_id, path, limit):
    if node_id == "local":
        with open(path, "rb") as f:
            return f.read(limit)
    ok, data, error = nodes.call(
        node_id, "fs_read", {"path": path, "offset": 0, "length": limit}, timeout=30)
    if not ok:
        raise IOError(error or "gagal membaca file di node")
    return base64.b64decode(data.get("data_b64") or "")


def _fs_write_bytes(node_id, path, data):
    if node_id == "local":
        with open(path, "wb") as f:
            f.write(data)
        return
    chunk = 262144
    if not data:
        ok, _, error = nodes.call(node_id, "fs_write",
                                  {"path": path, "data_b64": "", "append": False}, timeout=30)
        if not ok:
            raise IOError(error or "gagal menulis file di node")
        return
    first = True
    for i in range(0, len(data), chunk):
        ok, _, error = nodes.call(
            node_id, "fs_write",
            {"path": path, "data_b64": base64.b64encode(data[i:i + chunk]).decode(),
             "append": not first}, timeout=30)
        if not ok:
            raise IOError(error or "gagal menulis file di node")
        first = False


def _fs_mkdir(node_id, path):
    if node_id == "local":
        os.makedirs(path, exist_ok=True)
        try:
            os.chmod(path, 0o777)
        except Exception:
            pass
        return
    _sh(node_id, "mkdir -p %s && chmod 777 %s" % (shlex.quote(path), shlex.quote(path)), timeout=30)


def _fs_rmtree(node_id, path):
    if node_id == "local":
        shutil.rmtree(path, ignore_errors=True)
        return
    _sh(node_id, "rm -rf %s" % shlex.quote(path), timeout=60)


# ---------------- docker ----------------

def docker_ok(node_id="local"):
    if node_id == "local":
        return shutil.which("docker") is not None
    rep = nodes.node_report(node_id)
    return bool(rep and rep.get("docker"))


def cname(slug):
    return "rn-bot-" + slug


def _parse_container_lines(ps_out, stats_out):
    out = {}
    for line in ps_out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            out[parts[0]] = {"status_text": parts[1], "state": parts[2]}
    for line in stats_out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] in out:
            out[parts[0]]["mem"] = parts[1].split("/")[0].strip()
            out[parts[0]]["cpu"] = parts[2]
    return out


def container_info(node_id="local"):
    if not docker_ok(node_id):
        return {}
    ps_cmd = "docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.State}}'"
    st_cmd = "docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'"
    _, _, ps_out = _sh(node_id, ps_cmd, timeout=30)
    _, _, st_out = _sh(node_id, st_cmd, timeout=45)
    return _parse_container_lines(ps_out, st_out)


def _create_container(bot):
    rt = RUNTIMES[bot["runtime"]]
    tokens = ["docker", "create", "--name", cname(bot["slug"]),
              "--restart", "unless-stopped" if bot["auto_restart"] else "no",
              "--memory", "%dm" % int(bot["mem_limit_mb"]),
              "-v", "%s:%s" % (bot["dir"], WORKDIR), "-w", WORKDIR]
    for k, v in (bot.get("env") or {}).items():
        tokens += ["-e", "%s=%s" % (k, v)]
    tokens += [rt["image"], "sh", "-c", bot["start_cmd"]]
    cmd = " ".join(shlex.quote(t) for t in tokens)
    tok, rc, out = _sh(bot["node_id"], cmd, timeout=60)
    return (tok and rc == 0), out[-300:]


def _provision_worker(node_id, slug):
    key = _key(node_id, slug)

    def set_state(state, detail=""):
        with PROVISION_LOCK:
            PROVISION[key] = {"state": state, "detail": detail, "ts": int(time.time())}
    bot = get_bot(node_id, slug)
    if not bot:
        return
    try:
        set_state("menarik image runtime (bisa beberapa menit)")
        rt = RUNTIMES[bot["runtime"]]
        tok, rc, out = _sh(node_id, "docker pull %s" % shlex.quote(rt["image"]), timeout=1800)
        if not tok or rc != 0:
            set_state("gagal", (out or "docker pull gagal")[-300:])
            return
        set_state("membuat container")
        okk, msg = _create_container(bot)
        if not okk:
            set_state("gagal", msg)
            return
        set_state("selesai")
    except Exception as ex:
        set_state("gagal", str(ex)[-300:])


def remote_bots_dir(node_id):
    rep = nodes.node_report(node_id)
    if rep and rep.get("bots_dir"):
        return str(rep["bots_dir"])
    return REMOTE_BOTS_DEFAULT


def create_bot(node_id, name, runtime, start_cmd, mem_limit_mb, auto_restart, env):
    if runtime not in RUNTIMES:
        return None, "runtime tidak dikenal"
    if not docker_ok(node_id):
        return None, "docker tidak tersedia di node ini"
    slug = unique_slug(node_id, name)
    bot_dir = os.path.join(BOTS_DIR, slug) if node_id == "local" \
        else remote_bots_dir(node_id).rstrip("/") + "/" + slug
    _fs_mkdir(node_id, bot_dir)
    bot = {
        "slug": slug, "name": str(name)[:60] or slug, "runtime": runtime,
        "start_cmd": (start_cmd or RUNTIMES[runtime]["default_start"])[:300],
        "mem_limit_mb": max(64, min(2048, int(mem_limit_mb or 512))),
        "auto_restart": bool(auto_restart),
        "env": env or {}, "created_ts": int(time.time()), "dir": bot_dir,
        "node_id": node_id,
    }
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO bots (slug, name, runtime, start_cmd, mem_limit_mb, auto_restart, env_json, created_ts, node_id, dir)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bot["slug"], bot["name"], bot["runtime"], bot["start_cmd"], bot["mem_limit_mb"],
                 1 if bot["auto_restart"] else 0, json.dumps(bot["env"]), bot["created_ts"],
                 node_id, bot_dir))
            conn.commit()
        finally:
            conn.close()
    threading.Thread(target=_provision_worker, args=(node_id, slug), daemon=True).start()
    return bot, None


def bots_overview(node_id="local"):
    conts = container_info(node_id)
    out = []
    for bot in list_bots(node_id):
        c = conts.get(cname(bot["slug"]))
        with PROVISION_LOCK:
            prov = dict(PROVISION.get(_key(node_id, bot["slug"]), {}))
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
        "docker": docker_ok(node_id),
        "runtimes": [{"id": k, "label": v["label"], "image": v["image"],
                      "default_start": v["default_start"]} for k, v in RUNTIMES.items()],
        "bots": out,
    }


def bot_action(node_id, slug, action, wipe=False):
    bot = get_bot(node_id, slug)
    if not bot:
        return False, "bot tidak ditemukan"
    name = cname(slug)
    if action in ("start", "stop", "restart"):
        tok, rc, out = _sh(node_id, "docker %s %s" % (action, shlex.quote(name)), timeout=60)
        if not tok or rc != 0:
            return False, (out or "gagal")[-200:]
        return True, "ok"
    if action == "delete":
        _sh(node_id, "docker rm -f %s" % shlex.quote(name), timeout=60)
        with _db_lock:
            conn = _conn()
            try:
                conn.execute("DELETE FROM bots WHERE node_id = ? AND slug = ?", (node_id, slug))
                conn.commit()
            finally:
                conn.close()
        with PROVISION_LOCK:
            PROVISION.pop(_key(node_id, slug), None)
        if wipe:
            _fs_rmtree(node_id, bot["dir"])
        return True, "ok"
    return False, "aksi tidak dikenal"


def update_config(node_id, slug, start_cmd=None, mem_limit_mb=None, auto_restart=None, env=None):
    bot = get_bot(node_id, slug)
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
                "UPDATE bots SET start_cmd = ?, mem_limit_mb = ?, auto_restart = ?, env_json = ?"
                " WHERE node_id = ? AND slug = ?",
                (bot["start_cmd"], bot["mem_limit_mb"], 1 if bot["auto_restart"] else 0,
                 json.dumps(bot["env"]), node_id, slug))
            conn.commit()
        finally:
            conn.close()
    conts = container_info(node_id)
    if cname(slug) in conts:
        _sh(node_id, "docker rm -f %s" % shlex.quote(cname(slug)), timeout=60)
        okk, msg = _create_container(bot)
        if not okk:
            return False, "konfigurasi tersimpan tapi container gagal dibuat ulang: " + msg
    return True, "ok"


def bot_logs(node_id, slug, tail=200):
    if not get_bot(node_id, slug):
        return None
    tok, _, out = _sh(node_id, "docker logs --tail %d --timestamps %s"
                      % (int(tail), shlex.quote(cname(slug))), timeout=30)
    if not tok:
        return "(gagal mengambil log dari node: %s)" % out
    return out[-12000:]


def bot_exec(node_id, slug, cmd):
    bot = get_bot(node_id, slug)
    if not bot:
        return False, "bot tidak ditemukan"
    conts = container_info(node_id)
    info = conts.get(cname(slug))
    if not info or info["state"] != "running":
        return False, "bot tidak sedang berjalan — nyalakan dulu untuk menjalankan perintah"
    tok, _, out = _sh(
        node_id,
        "docker exec %s sh -c %s" % (shlex.quote(cname(slug)), shlex.quote(str(cmd)[:500])),
        timeout=30)
    if not tok:
        return False, out
    return True, out[-8000:]


# ---------------- install dependensi ----------------

def _install_worker(node_id, slug):
    key = _key(node_id, slug)

    def set_state(state, log=""):
        with INSTALL_LOCK:
            INSTALL_JOB[key] = {"state": state, "log": log[-8000:], "ts": int(time.time())}
    bot = get_bot(node_id, slug)
    if not bot:
        return
    rt = RUNTIMES[bot["runtime"]]
    marker = os.path.join(bot["dir"], rt["install_marker"])
    if not _fs_exists(node_id, marker):
        set_state("gagal", "Berkas %s tidak ditemukan di folder bot — unggah dulu kode botnya." % rt["install_marker"])
        return
    set_state("berjalan", "Menjalankan: %s\n" % rt["install_cmd"])
    tokens = ["docker", "run", "--rm", "--memory", "768m",
              "-v", "%s:%s" % (bot["dir"], WORKDIR), "-w", WORKDIR,
              rt["image"], "sh", "-c", rt["install_cmd"]]
    cmd = " ".join(shlex.quote(t) for t in tokens)
    tok, rc, out = _sh(node_id, cmd, timeout=1200)
    if not tok:
        set_state("gagal", out or "node tidak menjawab")
    elif rc == 0:
        set_state("selesai", out[-8000:] + "\n[install selesai]")
    elif rc == 124:
        set_state("gagal", "Install melewati batas 20 menit.")
    else:
        set_state("gagal", out[-8000:] + "\n[install gagal, kode %d]" % rc)


def start_install_deps(node_id, slug):
    if not get_bot(node_id, slug):
        return False
    with INSTALL_LOCK:
        cur = INSTALL_JOB.get(_key(node_id, slug), {})
        if cur.get("state") == "berjalan":
            return False
    threading.Thread(target=_install_worker, args=(node_id, slug), daemon=True).start()
    return True


def install_status(node_id, slug):
    with INSTALL_LOCK:
        return dict(INSTALL_JOB.get(_key(node_id, slug), {})) or None


# ---------------- editor berkas ----------------

def _bot_file(bot, rel):
    base = os.path.realpath(bot["dir"])
    p = os.path.realpath(os.path.join(base, (rel or "").lstrip("/")))
    if p != base and not p.startswith(base + "/"):
        return None
    return p


def read_bot_file(node_id, slug, rel):
    bot = get_bot(node_id, slug)
    if not bot:
        return None, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None or not _fs_exists(node_id, p):
        return None, "file tidak ditemukan"
    try:
        raw = _fs_read_bytes(node_id, p, MAX_EDIT_BYTES + 1)
    except Exception as ex:
        return None, str(ex)[:200]
    if len(raw) > MAX_EDIT_BYTES:
        return None, "file terlalu besar untuk editor (maks 512 KB)"
    if b"\x00" in raw[:8192]:
        return None, "file biner tidak bisa diedit di sini"
    return {"path": rel, "content": raw.decode("utf-8", "replace")}, None


def save_bot_file(node_id, slug, rel, content):
    bot = get_bot(node_id, slug)
    if not bot:
        return False, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None:
        return False, "jalur tidak diizinkan"
    data = str(content).encode("utf-8")
    if len(data) > MAX_EDIT_BYTES:
        return False, "isi melewati batas 512 KB"
    if node_id == "local" and not os.path.isdir(os.path.dirname(p)):
        return False, "folder tujuan tidak ada"
    try:
        _fs_write_bytes(node_id, p, data)
    except Exception as ex:
        return False, str(ex)[:200]
    return True, "ok"


def extract_zip(node_id, slug, rel):
    bot = get_bot(node_id, slug)
    if not bot:
        return False, "bot tidak ditemukan"
    p = _bot_file(bot, rel)
    if p is None:
        return False, "file zip tidak ditemukan"
    if node_id != "local":
        st_ok, st, _ = nodes.call(node_id, "fs_stat", {"path": p}, timeout=20)
        if not st_ok or not st or not st.get("is_file"):
            return False, "file zip tidak ditemukan"
        ok, data, error = nodes.call(
            node_id, "fs_extract_zip", {"path": p, "dest": bot["dir"]}, timeout=300)
        if not ok:
            return False, (error or "ekstrak gagal")[:200]
        return True, "%d file diekstrak" % int((data or {}).get("count", 0))
    if not os.path.isfile(p):
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
