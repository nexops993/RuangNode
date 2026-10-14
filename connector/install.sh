#!/usr/bin/env bash
# RuangNode Connector — pemasang agent satu perintah.
#
#   curl -fsSL https://raw.githubusercontent.com/nexops993/RuangNode/main/connector/install.sh | sudo bash -s -- --token <TOKEN>
#
# Opsi: --token <token dari dashboard> (wajib)
#       --url <alamat dashboard> (bawaan: https://api.ruangnode.me)
set -euo pipefail

TOKEN=""
URL="https://api.ruangnode.me"
RAW_BASE="https://raw.githubusercontent.com/nexops993/RuangNode/main/connector"

while [ $# -gt 0 ]; do
  case "$1" in
    --token) TOKEN="${2:-}"; shift 2 ;;
    --url) URL="${2:-}"; shift 2 ;;
    *) echo "argumen tidak dikenal: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$TOKEN" ]; then
  echo "ERROR: --token wajib diisi (ambil dari dialog Add Connector di dashboard)." >&2
  exit 1
fi

if [ "$(id -u)" != "0" ]; then
  echo "Skrip ini butuh root. Jalankan dengan sudo." >&2
  exit 1
fi

echo "== RuangNode Connector =="
echo "Dashboard : $URL"

# --- Python 3 (agent hanya memakai stdlib) ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "Memasang python3..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq python3 >/dev/null
  else
    echo "ERROR: python3 tidak ada dan apt-get tidak tersedia." >&2
    exit 1
  fi
fi
echo "Python    : $(python3 --version 2>&1)"

# --- Docker (syarat Panel Bot di node ini) ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker belum ada — memasang Docker (syarat Panel Bot)..."
  # Paket compose bawaan distro bisa bentrok file dengan plugin dari
  # repo Docker resmi — singkirkan dulu bila ada agar pemasangan mulus.
  if command -v apt-get >/dev/null 2>&1; then
    apt-get remove -y docker-compose-v2 docker-compose >/dev/null 2>&1 || true
  fi
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true
echo "Docker    : $(docker --version 2>/dev/null || echo 'terpasang')"

# --- Berkas agent ---
install -d -m 755 /opt/ruangnode-connector /opt/ruangnode/bots
install -d -m 700 /etc/ruangnode-connector
echo "Mengunduh agent..."
curl -fsSL "$RAW_BASE/agent.py" -o /opt/ruangnode-connector/agent.py
chmod 755 /opt/ruangnode-connector/agent.py

umask 077
cat > /etc/ruangnode-connector/config.json <<EOF
{"url": "$URL", "token": "$TOKEN"}
EOF
chmod 600 /etc/ruangnode-connector/config.json

# --- Service systemd ---
cat > /etc/systemd/system/ruangnode-agent.service <<'EOF'
[Unit]
Description=RuangNode Connector Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=AGENT_CONFIG=/etc/ruangnode-connector/config.json
ExecStart=/usr/bin/python3 /opt/ruangnode-connector/agent.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ruangnode-agent
sleep 3
if systemctl is-active --quiet ruangnode-agent; then
  echo "Agent aktif. Mesin ini akan muncul di sidebar dashboard dalam beberapa detik."
else
  echo "Agent belum aktif — periksa: journalctl -u ruangnode-agent -n 30" >&2
  exit 1
fi
