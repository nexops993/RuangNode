"""Multi-node: registri node agent + antrean perintah (RPC) + riwayat.

Dashboard bisa mengelola banyak mesin Linux. Node lokal ("local")
dihitung langsung; node lain menjalankan agent connector yang
terhubung KELUAR ke dashboard lewat HTTPS (tanpa port terbuka di
node): agent melapor statistik berkala dan mengambil perintah dari
antrean (poll), menjalankannya, lalu mengirim hasilnya kembali.
"""
import hashlib
import json
import secrets
import sqlite3
import threading
import time

from .config import db_path

LOCAL_ID = "local"
ONLINE_WINDOW_S = 40
RETENTION_S = 7 * 24 * 3600

_db_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS nodes ("
                " id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,"
                " hostname TEXT, os_name TEXT, created_ts INTEGER NOT NULL,"
                " last_seen INTEGER, report_json TEXT)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_commands ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL,"
                " type TEXT NOT NULL, payload_json TEXT NOT NULL,"
                " status TEXT NOT NULL DEFAULT 'pending', result_json TEXT,"
                " created_ts INTEGER NOT NULL, done_ts INTEGER)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS node_history ("
                " ts INTEGER NOT NULL, node_id TEXT NOT NULL,"
                " cpu REAL, mem REAL, temp REAL, PRIMARY KEY (ts, node_id))")
            conn.commit()
        finally:
            conn.close()


# ---------------- pendaftaran & autentikasi agent ----------------

def _hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def create_enroll(name):
    token = secrets.token_urlsafe(32)
    node_id = "node-" + secrets.token_hex(3)
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO nodes (id, name, token_hash, created_ts) VALUES (?, ?, ?, ?)",
                (node_id, str(name or "").strip()[:60] or "Node baru", _hash(token), int(time.time())))
            conn.commit()
        finally:
            conn.close()
    return {"id": node_id, "name": str(name or "").strip()[:60] or "Node baru", "token": token}


def auth_agent(token):
    if not token:
        return None
    h = _hash(token)
    with _db_lock:
        conn = _conn()
        try:
            r = conn.execute("SELECT * FROM nodes WHERE token_hash = ?", (h,)).fetchone()
        finally:
            conn.close()
    return dict(r) if r else None


def get_node(node_id):
    with _db_lock:
        conn = _conn()
        try:
            r = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        finally:
            conn.close()
    return dict(r) if r else None


def node_report(node_id):
    n = get_node(node_id)
    if not n or not n.get("report_json"):
        return None
    try:
        return json.loads(n["report_json"])
    except Exception:
        return None


# ---------------- laporan agent ----------------

def save_report(node_id, report):
    now = int(time.time())
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE nodes SET hostname = ?, os_name = ?, last_seen = ?, report_json = ? WHERE id = ?",
                (str(report.get("hostname") or "")[:120], str(report.get("os") or "")[:200],
                 now, json.dumps(report), node_id))
            # titik riwayat maks 1 per ±50 detik per node
            last = conn.execute(
                "SELECT MAX(ts) FROM node_history WHERE node_id = ?", (node_id,)).fetchone()[0]
            if last is None or now - last >= 50:
                mem = report.get("mem") or {}
                mem_pct = round(100.0 * mem.get("used", 0) / mem["total"], 1) if mem.get("total") else 0
                conn.execute(
                    "INSERT OR REPLACE INTO node_history (ts, node_id, cpu, mem, temp) VALUES (?, ?, ?, ?, ?)",
                    (now, node_id, report.get("cpu_pct"), mem_pct, report.get("temp_c")))
                conn.execute("DELETE FROM node_history WHERE ts < ?", (now - RETENTION_S,))
            conn.commit()
        finally:
            conn.close()


def history_query(node_id, hours):
    cutoff = int(time.time()) - hours * 3600
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT ts, cpu, mem, temp FROM node_history WHERE node_id = ? AND ts >= ? ORDER BY ts",
                (node_id, cutoff)).fetchall()
        finally:
            conn.close()
    pts = [{"ts": r[0], "cpu": r[1], "mem": r[2], "temp": r[3]} for r in rows]
    if not pts:
        return []
    bucket = max(1, len(pts) // 360)
    out = []
    for i in range(0, len(pts), bucket):
        grp = pts[i:i + bucket]
        temps = [g["temp"] for g in grp if g["temp"] is not None]
        out.append({
            "ts": grp[-1]["ts"],
            "cpu": round(sum(g["cpu"] for g in grp) / len(grp), 1),
            "mem": round(sum(g["mem"] for g in grp) / len(grp), 1),
            "temp": round(sum(temps) / len(temps), 1) if temps else None,
        })
    return out


# ---------------- daftar node untuk UI ----------------

def nodes_overview(local_summary):
    now = int(time.time())
    out = [dict(local_summary, id=LOCAL_ID, kind="local", online=True, last_seen=now)]
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM nodes ORDER BY created_ts").fetchall()
        finally:
            conn.close()
    for r in rows:
        rep = {}
        if r["report_json"]:
            try:
                rep = json.loads(r["report_json"])
            except Exception:
                rep = {}
        mem = rep.get("mem") or {}
        out.append({
            "id": r["id"], "kind": "agent",
            "name": r["name"],
            "hostname": r["hostname"] or rep.get("hostname") or "",
            "os": r["os_name"] or rep.get("os") or "",
            "online": bool(r["last_seen"]) and (now - (r["last_seen"] or 0)) <= ONLINE_WINDOW_S,
            "last_seen": r["last_seen"],
            "cpu_pct": rep.get("cpu_pct"),
            "mem_pct": round(100.0 * mem.get("used", 0) / mem["total"], 1) if mem.get("total") else None,
            "docker": bool(rep.get("docker")),
            "bots_dir": rep.get("bots_dir"),
        })
    return out


def delete_node(node_id):
    with _db_lock:
        conn = _conn()
        try:
            conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            conn.execute("DELETE FROM agent_commands WHERE node_id = ?", (node_id,))
            conn.execute("DELETE FROM node_history WHERE node_id = ?", (node_id,))
            conn.execute("DELETE FROM bots WHERE node_id = ?", (node_id,))
            conn.commit()
        finally:
            conn.close()


# ---------------- RPC: perintah ke agent ----------------

def call(node_id, ctype, payload, timeout=30):
    """Kirim perintah ke agent dan tunggu hasilnya. -> (ok, data, error)"""
    with _db_lock:
        conn = _conn()
        try:
            cur = conn.execute(
                "INSERT INTO agent_commands (node_id, type, payload_json, status, created_ts)"
                " VALUES (?, ?, ?, 'pending', ?)",
                (node_id, ctype, json.dumps(payload), int(time.time())))
            cmd_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _db_lock:
            conn = _conn()
            try:
                r = conn.execute(
                    "SELECT status, result_json FROM agent_commands WHERE id = ?", (cmd_id,)).fetchone()
            finally:
                conn.close()
        if r and r["status"] == "done":
            try:
                res = json.loads(r["result_json"] or "{}")
            except Exception:
                res = {}
            if res.get("ok"):
                return True, res.get("data"), None
            return False, None, str(res.get("error") or "perintah gagal di node")
        time.sleep(0.2)
    return False, None, "node tidak menjawab (timeout) — pastikan agent menyala & node online"


def poll_commands(node_id):
    now = int(time.time())
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT id, type, payload_json FROM agent_commands"
                " WHERE node_id = ? AND status = 'pending' ORDER BY id LIMIT 8",
                (node_id,)).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                conn.execute(
                    "UPDATE agent_commands SET status = 'sent' WHERE id IN (%s)"
                    % ",".join("?" * len(ids)), ids)
            # bersihkan perintah lama sesekali
            conn.execute("DELETE FROM agent_commands WHERE created_ts < ?", (now - 3600,))
            conn.commit()
        finally:
            conn.close()
    return [{"id": r["id"], "type": r["type"], "payload": json.loads(r["payload_json"])} for r in rows]


def save_result(node_id, cmd_id, ok, data, error):
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE agent_commands SET status = 'done', result_json = ?, done_ts = ?"
                " WHERE id = ? AND node_id = ?",
                (json.dumps({"ok": bool(ok), "data": data, "error": error}),
                 int(time.time()), int(cmd_id), node_id))
            conn.commit()
        finally:
            conn.close()
