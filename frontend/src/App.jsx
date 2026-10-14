import React, { useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, postJSON, fmtBytes, fmtPct, fmtUptime, fmtTemp } from "./api";
import * as I from "./icons";
import { UiCtx } from "./ui-context";
import { BotsSection } from "./bots";

const useUi = () => useContext(UiCtx);


/* ================= App ================= */

export default function App() {
  const [authed, setAuthed] = useState(null);
  const [toastMsg, setToastMsg] = useState(null);
  const [modal, setModal] = useState(null);
  const toastTimer = useRef(null);

  const toast = useCallback((msg) => {
    setToastMsg(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastMsg(null), 2600);
  }, []);
  const confirm = useCallback((title, body, onOk) => setModal({ title, body, onOk }), []);

  useEffect(() => {
    api("/api/me").then(({ j }) => setAuthed(!!(j && j.authed)));
  }, []);

  return (
    <UiCtx.Provider value={{ toast, confirm }}>
      {authed === null && <div style={{ padding: 24 }} className="muted">Memuat...</div>}
      {authed === false && <Login onLogin={() => setAuthed(true)} />}
      {authed === true && <Dashboard onLogout={() => setAuthed(false)} />}
      {toastMsg && <div id="toast" style={{ display: "block" }}>{toastMsg}</div>}
      {modal && (
        <div id="modal">
          <div className="box">
            <h3>{modal.title}</h3>
            <p>{modal.body}</p>
            <div className="acts">
              <button className="btn ghost" onClick={() => setModal(null)}>Batal</button>
              <button className="btn danger" onClick={() => { const f = modal.onOk; setModal(null); if (f) f(); }}>Ya, Lanjutkan</button>
            </div>
          </div>
        </div>
      )}
    </UiCtx.Provider>
  );
}

/* ================= Login ================= */

function Login({ onLogin }) {
  const [showForm, setShowForm] = useState(false);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");

  async function submit(e) {
    e.preventDefault();
    setErr("");
    const { r, j } = await postJSON("/login", { password: pw });
    if (r.ok) onLogin();
    else setErr((j && j.error) || "Login gagal (" + r.status + ")");
  }

  return (
    <div id="view-login">
      <div className="login-card">
        <div className="logo"><I.LogoIcon size={34} /></div>
        <h1>RuangNode</h1>
        <p>Dashboard Web Untuk Linux</p>
        {!showForm && (
          <button className="btn" style={{ width: "100%" }} onClick={() => setShowForm(true)}>
            <I.LockIcon /> Login
          </button>
        )}
        {showForm && (
          <form id="login-form" onSubmit={submit}>
            <label htmlFor="pw">Password dashboard</label>
            <input type="password" id="pw" autoComplete="current-password" placeholder="Masukkan password"
              value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
            {err && <div id="login-err" style={{ display: "block" }}>{err}</div>}
            <button className="btn" type="submit" style={{ width: "100%", marginTop: 12 }}>Masuk Dashboard</button>
          </form>
        )}
        <div className="login-note">Panel kendali server rumahan — akses hanya untuk pemilik.</div>
      </div>
    </div>
  );
}

/* ================= Dashboard ================= */

const TABS = [
  { id: "home", label: "Ringkasan", Icon: I.NavHome },
  { id: "files", label: "Penyimpanan", Icon: I.NavFiles },
  { id: "apps", label: "Aplikasi", Icon: I.NavApps },
  { id: "svc", label: "Service", Icon: I.NavSvc },
  { id: "sys", label: "Sistem", Icon: I.NavSys },
];

function Dashboard({ onLogout }) {
  const { toast } = useUi();
  const [tab, setTab] = useState("home");
  const [status, setStatus] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadStatus = useCallback(async () => {
    const { j } = await api("/api/status");
    if (j && j.ok) setStatus(j.data);
  }, []);

  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 4000);
    return () => clearInterval(t);
  }, [loadStatus]);

  async function logout() {
    await api("/logout", { method: "POST" });
    onLogout();
  }

  return (
    <div id="view-dash" style={{ display: "block" }}>
      <div className="wrap">
        <header className="top">
          <div className="mark"><I.LogoIcon size={22} /></div>
          <div>
            <h1>RuangNode</h1>
            <div className="sub">{status ? status.hostname : "Dashboard Web Untuk Linux"}</div>
          </div>
          <div className="sp"></div>
          <button className="icon-btn" title="Muat ulang" aria-label="Muat ulang"
            onClick={() => { loadStatus(); setRefreshKey((k) => k + 1); toast("Dimuat ulang"); }}>
            <I.RefreshIcon />
          </button>
          <button className="icon-btn" title="Keluar" aria-label="Keluar" onClick={logout}>
            <I.LogoutIcon />
          </button>
        </header>

        {tab === "home" && <HomePane status={status} refreshKey={refreshKey} />}
        {tab === "files" && <FilesPane refreshKey={refreshKey} />}
        {tab === "apps" && <AppsPane refreshKey={refreshKey} />}
        {tab === "svc" && <ServicesPane refreshKey={refreshKey} />}
        {tab === "sys" && <SystemPane status={status} />}
      </div>

      <nav className="tabs">
        {TABS.map(({ id, label, Icon }) => (
          <button key={id} className={tab === id ? "act" : ""} onClick={() => setTab(id)}>
            <Icon />{label}
          </button>
        ))}
      </nav>
    </div>
  );
}

/* ================= Ringkasan ================= */

function Chart({ points, k, unit, fixedMax }) {
  const vals = points.map((p) => p[k]).filter((v) => v != null);
  if (!points.length || !vals.length)
    return (<svg viewBox="0 0 300 64" preserveAspectRatio="none" style={{ width: "100%", height: 64, display: "block" }}>
      <text x="6" y="36" fontSize="11" fill="#8a7362">belum ada data pada rentang ini</text></svg>);
  const max = fixedMax || Math.max(...vals) * 1.15 || 1;
  const W = 300, H = 64, PAD = 3;
  const x = (i) => (points.length === 1 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (points.length - 1));
  const y = (v) => H - PAD - (v / max) * (H - 2 * PAD);
  let line = "", started = false;
  points.forEach((p, i) => {
    if (p[k] == null) return;
    line += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(p[k]).toFixed(1) + " ";
    started = true;
  });
  const area = line + "L" + x(points.length - 1) + " " + H + " L" + x(0) + " " + H + " Z";
  return (
    <svg viewBox="0 0 300 64" preserveAspectRatio="none" style={{ width: "100%", height: 64, display: "block" }}>
      <path d={area} fill="rgba(192,95,51,.14)" />
      <path d={line} fill="none" stroke="#c05f33" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function chartStat(points, k, unit) {
  const vals = points.map((p) => p[k]).filter((v) => v != null);
  if (!vals.length) return "–";
  const cur = vals[vals.length - 1], mx = Math.max(...vals), avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  return "sekarang " + cur + unit + " · maks " + mx + unit + " · rata-rata " + Math.round(avg) + unit;
}

function HomePane({ status, refreshKey }) {
  const [hours, setHours] = useState(24);
  const [points, setPoints] = useState([]);

  const loadHistory = useCallback(async () => {
    const { j } = await api("/api/history?hours=" + hours);
    if (j && j.ok) setPoints(j.data.points);
  }, [hours]);

  useEffect(() => {
    loadHistory();
    const t = setInterval(loadHistory, 60000);
    return () => clearInterval(t);
  }, [loadHistory, refreshKey]);

  const d = status;
  const ramPct = d && d.mem.total ? Math.round((100 * d.mem.used) / d.mem.total) : null;
  const rootPct = d ? Math.round((100 * d.disk_root.used) / d.disk_root.total) : 0;
  const dataPct = d && d.disk_data ? Math.round((100 * d.disk_data.used) / d.disk_data.total) : 0;

  return (
    <div className="pane act">
      <div className="grid">
        <div className="card stat">
          <div className="lbl"><I.CpuIcon />CPU</div>
          <div className="val">{d ? fmtPct(d.cpu_pct) : "–"}</div>
          <div className="sub2">{d ? "load " + d.load.map((v) => v.toLocaleString("id-ID", { maximumFractionDigits: 2 })).join(" · ") : "load –"}</div>
        </div>
        <div className="card stat">
          <div className="lbl"><I.RamIcon />RAM</div>
          <div className="val">{ramPct != null ? ramPct + "%" : "–"}</div>
          <div className="sub2">{d ? fmtBytes(d.mem.used) + " dari " + fmtBytes(d.mem.total) : "–"}</div>
          <div className="bar"><i style={{ width: (ramPct || 0) + "%" }}></i></div>
        </div>
        <div className="card stat">
          <div className="lbl"><I.TempIcon />Suhu</div>
          <div className="val">{d ? fmtTemp(d.temp_c) : "–"}</div>
          <div className="sub2">SoC</div>
        </div>
        <div className="card stat">
          <div className="lbl"><I.ClockIcon />Uptime</div>
          <div className="val">{d ? fmtUptime(d.uptime_s) : "–"}</div>
          <div className="sub2">{d ? (d.net.iface || "jaringan –") : "jaringan –"}</div>
        </div>
      </div>

      <section className="blk">
        <h2><I.DiskIcon />Penyimpanan</h2>
        <div className="card pad">
          <div className="kv"><span>Disk internal (/)</span><b>{d ? "bebas " + fmtBytes(d.disk_root.free) + " dari " + fmtBytes(d.disk_root.total) : "–"}</b></div>
          <div className="bar"><i style={{ width: rootPct + "%" }}></i></div>
          <div className="kv" style={{ marginTop: 8 }}><span>Kartu SD (/data)</span><b>{d && d.disk_data ? "bebas " + fmtBytes(d.disk_data.free) + " dari " + fmtBytes(d.disk_data.total) : "tidak terpasang"}</b></div>
          <div className="bar"><i style={{ width: dataPct + "%" }}></i></div>
        </div>
      </section>

      <section className="blk">
        <h2><I.GlobeIcon />Jaringan</h2>
        <div className="card pad">
          <div className="kv"><span>IP Tailscale</span><b>{d ? (d.tailscale_ip || "–") : "–"}</b></div>
          <div className="kv"><span>IP lokal (WiFi)</span><b>{d ? (d.lan_ip || "–") : "–"}</b></div>
          <div className="kv"><span>Unduh / Unggah</span><b>{d ? fmtBytes(d.net.rx_bps) + "/s · " + fmtBytes(d.net.tx_bps) + "/s" : "–"}</b></div>
        </div>
      </section>

      <section className="blk">
        <h2><I.PulseIcon />Riwayat</h2>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          {[1, 6, 24, 168].map((h) => (
            <button key={h} className={"btn sm" + (hours === h ? "" : " ghost")} onClick={() => setHours(h)}>
              {h === 1 ? "1 jam" : h === 6 ? "6 jam" : h === 24 ? "24 jam" : "7 hari"}
            </button>
          ))}
        </div>
        {[["CPU", "cpu", "%", 100], ["RAM", "mem", "%", 100], ["Suhu SoC", "temp", "°C", null]].map(([label, k, unit, fm], idx) => (
          <div className="card pad" style={{ marginBottom: idx < 2 ? 8 : 0 }} key={k}>
            <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>{label}</span><b>{chartStat(points, k, unit)}</b></div>
            <Chart points={points} k={k} unit={unit} fixedMax={fm} />
          </div>
        ))}
        <p className="muted" style={{ marginTop: 8 }}>
          {points.length < 3
            ? "Riwayat baru mulai dicatat — grafik akan terisi seiring menit berjalan. Data disimpan 7 hari."
            : "Data dicatat tiap menit dan disimpan 7 hari. Rentang: " + hours + " jam, " + points.length + " titik."}
        </p>
      </section>
    </div>
  );
}

/* ================= Penyimpanan ================= */

function FilesPane({ refreshKey }) {
  const { toast } = useUi();
  const [path, setPath] = useState("/");
  const [items, setItems] = useState(null);
  const [upStatus, setUpStatus] = useState("");

  const load = useCallback(async (p) => {
    const { j } = await api("/api/files?path=" + encodeURIComponent(p));
    if (j && j.ok) { setItems(j.data.items); setPath(j.data.path); }
    else { setItems([]); toast("Gagal memuat folder: " + ((j && j.error) || "")); }
  }, [toast]);

  useEffect(() => { load(path); }, [refreshKey]);  // eslint-disable-line

  const parent = path === "/" ? null : path.replace(/\/[^/]+\/?$/, "") || "/";

  async function onUpload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("file", f));
    setUpStatus("Mengunggah " + files.length + " file...");
    const { r, j } = await api("/api/upload?path=" + encodeURIComponent(path), { method: "POST", body: fd });
    setUpStatus("");
    if (r.ok) { toast("Terunggah: " + (j.data.saved || []).join(", ")); load(path); }
    else toast("Gagal unggah: " + ((j && j.error) || r.status));
  }

  return (
    <div className="pane act">
      <section className="blk" style={{ marginTop: 4 }}>
        <h2><I.FolderIcon />File Manager — Seluruh Disk</h2>
        <div className="card pad">
          <div className="pathbar" style={{ marginBottom: 10 }}>
            <button className="btn sm ghost" onClick={() => load("/")}>Sistem (/)</button>
            <button className="btn sm ghost" onClick={() => load("/data")}>Kartu SD (/data)</button>
          </div>
          <div className="pathbar">
            {parent && <button onClick={() => load(parent)}>← Naik</button>}
            <span className="crumb">{path}</span>
            <span style={{ flex: 1 }}></span>
            <label className="btn sm" htmlFor="up-file" style={{ cursor: "pointer" }}>
              <I.UploadIcon /> Unggah
            </label>
            <input type="file" id="up-file" multiple style={{ display: "none" }} onChange={onUpload} />
          </div>
          {upStatus && <div className="muted">{upStatus}</div>}
          <div>
            {items === null && <p className="muted">Memuat...</p>}
            {items !== null && items.length === 0 && <p className="muted">Folder kosong</p>}
            {(items || []).map((it) => {
              const full = (path === "/" ? "" : path) + "/" + it.name;
              return (
                <div className="row" key={it.name}>
                  <div className="ficon">{it.dir ? <I.FolderRowIcon /> : <I.FileRowIcon />}</div>
                  <div className="grow">
                    {it.dir
                      ? <button className="nm" style={{ textAlign: "left", padding: 0 }} onClick={() => load(full)}>{it.name}</button>
                      : <a className="nm" style={{ color: "inherit", textDecoration: "none" }} href={"/api/download?path=" + encodeURIComponent(full)}>{it.name}</a>}
                    <div className="meta">{it.dir ? "folder" : fmtBytes(it.size)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}

/* ================= Aplikasi ================= */

function AppsPane({ refreshKey }) {
  return (
    <div className="pane act">
      <BotsSection refreshKey={refreshKey} />
    </div>
  );
}

/* ================= Service ================= */

function ServicesPane({ refreshKey }) {
  const { toast } = useUi();
  const [services, setServices] = useState(null);
  const [unit, setUnit] = useState("ruangnode-dashboard");
  const [logs, setLogs] = useState(null);

  const load = useCallback(async () => {
    const { j } = await api("/api/services");
    if (j && j.ok) setServices(j.data);
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const loadLogs = useCallback(async (u) => {
    setLogs("Memuat...");
    const { j } = await api("/api/logs?unit=" + encodeURIComponent(u) + "&lines=120");
    setLogs(j && j.ok ? (j.data.logs || "(tidak ada log)") : "Gagal memuat log");
  }, []);

  async function act(name, action) {
    const { r, j } = await postJSON("/api/service", { name, action });
    toast(r.ok ? name + ": " + action + " berhasil" : "Gagal: " + ((j && j.error) || r.status));
    setTimeout(load, 700);
  }

  return (
    <div className="pane act">
      <section className="blk" style={{ marginTop: 4 }}>
        <h2><I.SlidersIcon />Service Sistem</h2>
        <div className="card pad">
          {services === null && <p className="muted">Memuat...</p>}
          {(services || []).map((s) => (
            <div className="row" key={s.name}>
              <span className={"dot " + (s.status === "active" ? "on" : s.status === "inactive" ? "off" : "unk")}></span>
              <div className="grow">
                <div className="nm">{s.name}</div>
                <div className="meta">{s.status}{s.mode === "status-only" ? " · dipantau saja" : s.mode === "restart-only" ? " · hanya restart" : ""}</div>
              </div>
              {s.mode === "full" && s.status !== "active" && <button className="btn sm ghost" onClick={() => act(s.name, "start")}>Start</button>}
              {s.mode === "full" && s.status === "active" && <button className="btn sm ghost" onClick={() => act(s.name, "stop")}>Stop</button>}
              {(s.mode === "full" || s.mode === "restart-only") && <button className="btn sm ghost" onClick={() => act(s.name, "restart")}>Restart</button>}
            </div>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 10 }}>
          Service kritikal (Tailscale, SSH) hanya bisa di-restart dari sini — menghentikannya akan memutus akses jarak jauh ke STB. Service dashboard dan tunnel hanya dipantau.
        </p>
      </section>
      <section className="blk">
        <h2><I.FileTextIcon />Log Sistem</h2>
        <div className="card pad">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select className="select" value={unit} onChange={(e) => { setUnit(e.target.value); loadLogs(e.target.value); }}>
              <option value="ruangnode-dashboard">ruangnode-dashboard</option>
              <option value="cloudflared">cloudflared (tunnel)</option>
              <option value="tailscaled">tailscaled</option>
              <option value="ssh">ssh</option>
              <option value="docker">docker</option>
              <option value="containerd">containerd</option>
              <option value="sistem">Sistem (semua)</option>
            </select>
            <button className="btn sm" onClick={() => loadLogs(unit)}>Muat Log</button>
          </div>
          {logs !== null
            ? <pre className="logs">{logs}</pre>
            : <p className="muted" style={{ marginBottom: 0 }}>Pilih service lalu muat 120 baris log terakhirnya.</p>}
        </div>
      </section>
    </div>
  );
}

/* ================= Sistem ================= */

function SystemPane({ status }) {
  const { toast, confirm } = useUi();
  const d = status;

  function power(action, label) {
    confirm(label + " STB?",
      action === "reboot"
        ? "STB akan menyala ulang. Dashboard tidak bisa diakses selama beberapa puluh detik."
        : "STB akan mati total. Menyalakannya lagi harus dari tombol fisik di perangkat.",
      async () => {
        const { r, j } = await postJSON("/api/power", { action, confirm: true });
        toast(r.ok ? label + " dijadwalkan..." : "Gagal: " + ((j && j.error) || r.status));
      });
  }

  return (
    <div className="pane act">
      <section className="blk" style={{ marginTop: 4 }}>
        <h2><I.GearIcon />Perangkat</h2>
        <div className="card pad">
          <div className="kv"><span>Hostname</span><b>{d ? d.hostname : "–"}</b></div>
          <div className="kv"><span>Sistem operasi</span><b>{d ? d.os : "–"}</b></div>
          <div className="kv"><span>Kernel</span><b>{d ? d.kernel : "–"}</b></div>
          <div className="kv"><span>Arsitektur</span><b>{d ? d.arch : "–"}</b></div>
          <div className="kv"><span>Swap terpakai</span><b>{d ? fmtBytes(d.mem.swap_used) + " dari " + fmtBytes(d.mem.swap_total) : "–"}</b></div>
        </div>
      </section>
      <section className="blk">
        <h2><I.PowerIcon />Daya</h2>
        <div className="card pad">
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn ghost" style={{ flex: 1 }} onClick={() => power("reboot", "Reboot")}>
              <I.RebootIcon /> Reboot
            </button>
            <button className="btn danger" style={{ flex: 1 }} onClick={() => power("shutdown", "Matikan")}>
              <I.PowerBtnIcon /> Matikan
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            STB butuh beberapa puluh detik untuk menyala lagi setelah reboot. Setelah dimatikan, menyalakannya kembali harus dari tombol fisik di perangkat.
          </p>
        </div>
      </section>
    </div>
  );
}
