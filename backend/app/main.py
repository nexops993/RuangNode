"""RuangNode — Dashboard Web Untuk Linux (backend FastAPI).

Refactor fullstack dari dashboard monolit versi pertama: kontrak API
dan skema sesi dipertahankan persis, penyimpanan riwayat pindah ke
SQLite, frontend adalah aplikasi React/Vite terpisah yang hasil
build-nya dilayani dari folder frontend/dist.
"""
import os
import subprocess
import threading
from urllib.parse import unquote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import bots, files as filemod, history, logs as logmod, system
from .config import CFG, frontend_dist
from .security import (COOKIE_NAME, brute_check, brute_clear, brute_record,
                       client_ip, is_authed, make_session, require_auth,
                       verify_password)

app = FastAPI(title="RuangNode Dashboard", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(HTTPException)
def _http_exc_handler(request: Request, exc: HTTPException):
    # Samakan bentuk error dengan kontrak lama: {"ok": false, "error": ...}
    return JSONResponse(status_code=exc.status_code,
                        content={"ok": False, "error": str(exc.detail)})

MAX_UPLOAD = 1_073_741_824  # 1 GB


def ok(data):
    return {"ok": True, "data": data}


def err(code, msg):
    return JSONResponse(status_code=code, content={"ok": False, "error": msg})


# ---------------- autentikasi ----------------

@app.get("/api/me")
def me(request: Request):
    return {"ok": True, "authed": is_authed(request)}


@app.post("/login")
async def login(request: Request):
    ip = client_ip(request)
    if brute_check(ip):
        return err(429, "terlalu banyak percobaan gagal, coba lagi dalam 15 menit")
    data = await request.json()
    pw = str(data.get("password") or "")
    if CFG["PASSWORD_HASH"] and verify_password(pw, CFG["PASSWORD_HASH"]):
        brute_clear(ip)
        token = make_session(CFG["SESSION_SECRET"])
        resp = JSONResponse(content={"ok": True})
        resp.set_cookie(COOKIE_NAME, token, max_age=7 * 24 * 3600,
                        path="/", httponly=True, secure=True, samesite="lax")
        return resp
    brute_record(ip)
    return err(401, "password salah")


@app.post("/logout")
def logout():
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


# ---------------- status & service ----------------

@app.get("/api/status", dependencies=[Depends(require_auth)])
def status():
    return ok(system.system_status())


@app.get("/api/services", dependencies=[Depends(require_auth)])
def services():
    return ok(system.services_info())


@app.post("/api/service", dependencies=[Depends(require_auth)])
async def service_action(request: Request):
    data = await request.json()
    name = str(data.get("name") or "")
    action = str(data.get("action") or "")
    if name not in system.SERVICE_LIST or not system.unit_exists(name):
        return err(400, "service tidak dikenal")
    if action not in ("start", "stop", "restart"):
        return err(400, "aksi tidak dikenal")
    if name in system.STATUS_ONLY:
        return err(403, "service ini hanya bisa dipantau dari dashboard")
    if name in system.PROTECTED_RESTART_ONLY and action != "restart":
        return err(403, "service kritikal: hanya restart yang diizinkan (menghentikan memutus akses jarak jauh)")
    if name in system.FULL_CONTROL or name in system.PROTECTED_RESTART_ONLY:
        r = subprocess.run(["systemctl", action, name], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return err(500, (r.stderr or "gagal")[:200])
        return ok({"name": name, "status": system.service_status(name)})
    return err(403, "tidak diizinkan")


@app.post("/api/power", dependencies=[Depends(require_auth)])
async def power(request: Request):
    data = await request.json()
    action = str(data.get("action") or "")
    if action not in ("reboot", "shutdown") or data.get("confirm") is not True:
        return err(400, "aksi daya butuh konfirmasi")
    verb = "reboot" if action == "reboot" else "poweroff"
    subprocess.Popen(["sh", "-c", "sleep 2; systemctl %s" % verb])
    return ok({"scheduled": action})


# ---------------- riwayat & log ----------------

@app.get("/api/history", dependencies=[Depends(require_auth)])
def history_api(hours: int = 24):
    if hours not in (1, 6, 24, 168):
        hours = 24
    return ok({"hours": hours, "points": history.query(hours)})


@app.get("/api/logs", dependencies=[Depends(require_auth)])
def logs_api(unit: str = "ruangnode-dashboard", lines: int = 120):
    if unit not in logmod.LOG_UNITS:
        return err(400, "unit tidak dikenal")
    try:
        return ok({"unit": unit, "logs": logmod.system_logs(unit, lines)})
    except Exception as ex:
        return err(500, str(ex)[:200])


# ---------------- panel bot ----------------

@app.get("/api/bots", dependencies=[Depends(require_auth)])
def bots_list():
    return ok(bots.bots_overview())


@app.post("/api/bots/create", dependencies=[Depends(require_auth)])
async def bots_create(request: Request):
    data = await request.json()
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    bot, msg = bots.create_bot(
        str(data.get("name") or ""), str(data.get("runtime") or ""),
        str(data.get("start_cmd") or ""), data.get("mem_limit_mb") or 512,
        data.get("auto_restart", True), env)
    if bot is None:
        return err(400, msg)
    return ok({"slug": bot["slug"], "dir": bot["dir"]})


@app.post("/api/bots/action", dependencies=[Depends(require_auth)])
async def bots_action(request: Request):
    data = await request.json()
    done, msg = bots.bot_action(str(data.get("id") or ""), str(data.get("action") or ""),
                                wipe=bool(data.get("wipe")))
    if done:
        return ok({"done": True})
    return err(400, msg)


@app.post("/api/bots/config", dependencies=[Depends(require_auth)])
async def bots_config(request: Request):
    data = await request.json()
    env = data.get("env") if isinstance(data.get("env"), dict) else None
    done, msg = bots.update_config(
        str(data.get("id") or ""),
        start_cmd=data.get("start_cmd"), mem_limit_mb=data.get("mem_limit_mb"),
        auto_restart=data.get("auto_restart"), env=env)
    if done:
        return ok({"done": True})
    return err(400, msg)


@app.get("/api/bots/logs", dependencies=[Depends(require_auth)])
def bots_logs(id: str = "", tail: int = 200):
    logs = bots.bot_logs(id, tail)
    if logs is None:
        return err(400, "bot tidak ditemukan")
    return ok({"id": id, "logs": logs})


@app.post("/api/bots/exec", dependencies=[Depends(require_auth)])
async def bots_exec(request: Request):
    data = await request.json()
    done, out = bots.bot_exec(str(data.get("id") or ""), str(data.get("cmd") or ""))
    if done:
        return ok({"output": out})
    return err(400, out)


@app.post("/api/bots/install-deps", dependencies=[Depends(require_auth)])
async def bots_install_deps(request: Request):
    data = await request.json()
    if not bots.start_install_deps(str(data.get("id") or "")):
        return err(409, "install sedang berjalan atau bot tidak ditemukan")
    return ok({"started": True})


@app.get("/api/bots/install-status", dependencies=[Depends(require_auth)])
def bots_install_status(id: str = ""):
    st = bots.install_status(id)
    return ok(st or {"state": "belum pernah"})


@app.get("/api/bots/file", dependencies=[Depends(require_auth)])
def bots_file_read(id: str = "", path: str = ""):
    data, msg = bots.read_bot_file(id, path)
    if data is None:
        return err(400, msg)
    return ok(data)


@app.post("/api/bots/file/save", dependencies=[Depends(require_auth)])
async def bots_file_save(request: Request):
    data = await request.json()
    done, msg = bots.save_bot_file(str(data.get("id") or ""), str(data.get("path") or ""),
                                   data.get("content") or "")
    if done:
        return ok({"saved": True})
    return err(400, msg)


@app.post("/api/bots/extract", dependencies=[Depends(require_auth)])
async def bots_extract(request: Request):
    data = await request.json()
    done, msg = bots.extract_zip(str(data.get("id") or ""), str(data.get("path") or ""))
    if done:
        return ok({"message": msg})
    return err(400, msg)


# ---------------- berkas ----------------

@app.get("/api/files", dependencies=[Depends(require_auth)])
def files_list(path: str = ""):
    target = filemod.jail_path(path)
    if not os.path.isdir(target):
        return err(404, "folder tidak ada")
    try:
        items = filemod.list_dir(target)
    except Exception as ex:
        return err(500, str(ex))
    return ok({"path": target, "items": items})


@app.get("/api/download", dependencies=[Depends(require_auth)])
def files_download(path: str = ""):
    target = filemod.jail_path(path)
    # /proc, /sys, /dev adalah filesystem virtual kernel, bukan file
    # tersimpan - mengunduhnya bisa menggantung; tolak dengan jelas.
    if filemod.is_virtual(target):
        return err(400, "filesystem virtual sistem tidak bisa diunduh")
    if not os.path.isfile(target):
        return err(404, "file tidak ada")
    return FileResponse(target, filename=os.path.basename(target))


@app.post("/api/upload", dependencies=[Depends(require_auth)])
async def files_upload(path: str = "", file: list[UploadFile] = File(...)):
    dest_dir = filemod.jail_path(path)
    if not os.path.isdir(dest_dir):
        return err(400, "folder tujuan tidak valid")
    # periksa semua nama dulu: satu konflik membatalkan seluruh unggahan
    names = []
    for up in file:
        fname = os.path.basename(unquote(up.filename or ""))
        if not fname or fname.startswith("."):
            continue
        if os.path.exists(os.path.join(dest_dir, fname)):
            return err(409, "file '%s' sudah ada" % fname)
        names.append((up, fname))
    if not names:
        return err(400, "tidak ada file yang diterima")
    saved = []
    for up, fname in names:
        dest = os.path.join(dest_dir, fname)
        size = 0
        with open(dest, "wb") as f:
            while True:
                chunk = await up.read(262144)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD:
                    f.close()
                    os.unlink(dest)
                    return err(413, "ukuran unggahan melewati batas 1 GB")
                f.write(chunk)
        saved.append(fname)
    return ok({"saved": saved})


# ---------------- frontend statis ----------------

@app.on_event("startup")
def _startup():
    history.init_db()
    bots.init_db()
    threading.Thread(target=system.sampler, daemon=True).start()
    threading.Thread(target=history.writer, daemon=True).start()


_dist = frontend_dist()
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
