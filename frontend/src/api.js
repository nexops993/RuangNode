export async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    let j = null;
    try { j = await r.json(); } catch (e) { /* respons non-JSON */ }
    return { r, j };
  } catch (e) {
    return { r: { ok: false, status: 0 }, j: null };
  }
}

export function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const idID = (v, digits = 1) =>
  v.toLocaleString("id-ID", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export function fmtBytes(b) {
  if (b == null || isNaN(b)) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = b, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return idID(v, v >= 100 || i === 0 ? 0 : 1) + " " + units[i];
}

export function fmtPct(v) {
  if (v == null) return "–";
  return idID(v, 1) + "%";
}

export function fmtUptime(s) {
  if (!s && s !== 0) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return d + " hr " + h + " jm";
  if (h > 0) return h + " jm " + m + " mnt";
  return m + " mnt";
}

export function fmtTemp(t) {
  if (t == null) return "–";
  return idID(t, 1) + "°C";
}
