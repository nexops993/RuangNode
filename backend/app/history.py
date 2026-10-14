"""Riwayat metrik di SQLite: satu titik per menit, retensi 7 hari.

Saat pertama jalan, data lama dari history.jsonl (versi dashboard
sebelumnya) diimpor otomatis agar grafik tidak mulai dari nol.
"""
import json
import os
import sqlite3
import threading
import time

from .config import db_path
from .system import CACHE, CACHE_LOCK, mem_info

RETENTION_S = 7 * 24 * 3600
_db_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _db_lock:
        conn = _conn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS history ("
                " ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, temp REAL)"
            )
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            if count == 0:
                _import_legacy(conn)
        finally:
            conn.close()


def _import_legacy(conn):
    legacy_dir = os.path.dirname(db_path())
    legacy = os.path.join(legacy_dir, "history.jsonl")
    if not os.path.exists(legacy):
        return
    rows = []
    try:
        with open(legacy) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                    rows.append((int(p["ts"]), float(p["cpu"]), float(p["mem"]),
                                 float(p["temp"]) if p.get("temp") is not None else None))
                except Exception:
                    continue
    except Exception:
        return
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO history (ts, cpu, mem, temp) VALUES (?, ?, ?, ?)", rows)
        conn.commit()


def _point():
    with CACHE_LOCK:
        cache = dict(CACHE)
    mem = mem_info()
    return (
        int(time.time()),
        cache["cpu_pct"],
        round(100.0 * mem["used"] / mem["total"], 1) if mem["total"] else 0,
        cache["temp_c"],
    )


def writer():
    # titik pertama langsung saat aplikasi menyala, lalu tiap 60 detik
    while True:
        try:
            ts, cpu, mem_pct, temp = _point()
            with _db_lock:
                conn = _conn()
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO history (ts, cpu, mem, temp) VALUES (?, ?, ?, ?)",
                        (ts, cpu, mem_pct, temp))
                    conn.execute("DELETE FROM history WHERE ts < ?", (ts - RETENTION_S,))
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass
        time.sleep(60)


def query(hours):
    cutoff = int(time.time()) - hours * 3600
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT ts, cpu, mem, temp FROM history WHERE ts >= ? ORDER BY ts",
                (cutoff,)).fetchall()
        finally:
            conn.close()
    pts = [{"ts": r[0], "cpu": r[1], "mem": r[2], "temp": r[3]} for r in rows]
    if not pts:
        return []
    # gabungkan jadi maksimal ~360 titik (rata-rata per kelompok)
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
