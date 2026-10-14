"""Manajer berkas — akses penuh seluruh disk (pilihan pemilik, opsi C)."""
import os

VIRTUAL_FS = ("/proc", "/sys", "/dev")


def jail_path(rel):
    # Jail = seluruh filesystem "/". Path selalu dinormalisasi realpath
    # sehingga ".." tidak pernah bisa keluar dari root.
    p = rel or "/"
    if not p.startswith("/"):
        p = "/" + p
    return os.path.realpath(p)


def is_virtual(target):
    return target in VIRTUAL_FS or target.startswith(tuple(v + "/" for v in VIRTUAL_FS))


def list_dir(target):
    items = []
    with os.scandir(target) as it:
        for e in it:
            try:
                st = e.stat()
                items.append({
                    "name": e.name,
                    "dir": e.is_dir(),
                    "size": st.st_size if not e.is_dir() else None,
                    "mtime": int(st.st_mtime),
                })
            except Exception:
                continue
    items.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return items
