# RuangNode

Ruang Node - Dashboard Linux Server

Dashboard web untuk mengelola server Linux dari browser (mobile-first):
status sistem, riwayat metrik, file manager, service systemd, dan Panel
Bot ala Pterodactyl (tiap bot = satu container Docker dengan runtime
Node.js / Python, folder kerja, batas RAM, dan variabel env sendiri).

## Struktur

- `backend/` — API FastAPI (uvicorn), data di SQLite.
- `frontend/` — UI React + Vite (tema Claymorphism).
- `connector/` — agent penghubung untuk node tambahan (lihat di bawah).

## Menjalankan dashboard

Backend melayani hasil build frontend dari `frontend/dist`:

```bash
cd frontend && npm install && npm run build
cd ../backend && python -m venv .venv && .venv/bin/pip install fastapi uvicorn python-multipart
DASH_ENV_FILE=/etc/ruangnode-dashboard/env .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8091
```

Berkas env berisi `PASSWORD_HASH` (pbkdf2) dan `SESSION_SECRET`.

## Connector (menambah node)

Satu dashboard bisa mengelola banyak mesin. Di mesin baru, jalankan
perintah satu baris dari dialog **Add Connector** di sidebar dashboard
(token pendaftaran dibuatkan dashboard):

```bash
curl -fsSL https://raw.githubusercontent.com/nexops993/RuangNode/main/connector/install.sh | sudo bash -s -- --token <TOKEN>
```

Skrip memasang agent `ruangnode-agent` (Python murni, tanpa dependensi)
sebagai service systemd. Agent terhubung keluar ke dashboard lewat
HTTPS — tidak ada port yang perlu dibuka di mesin baru. Bila Docker
belum ada, skrip memasangnya (syarat Panel Bot di node tersebut).
