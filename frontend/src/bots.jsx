import React, { useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, postJSON, fmtBytes } from "./api";
import * as I from "./icons";

/* Konteks UI (toast & modal) dibagikan dari App lewat ui-context. */
import { UiCtx } from "./ui-context";

const useUi = () => useContext(UiCtx);

const PROVISIONING = ["menarik image runtime (bisa beberapa menit)", "membuat container"];

function TerminalIcon({ size = 17 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#c05f33" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3" /><path d="M12 15h5" />
    </svg>
  );
}

function envToText(env) {
  return Object.entries(env || {}).map(([k, v]) => k + "=" + v).join("\n");
}
function textToEnv(text) {
  const out = {};
  (text || "").split("\n").forEach((line) => {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) return;
    const idx = t.indexOf("=");
    out[t.slice(0, idx).trim()] = t.slice(idx + 1).trim();
  });
  return out;
}
function memToMB(s) {
  if (!s) return null;
  const m = String(s).match(/([\d.]+)\s*([KMG]i?B)/i);
  if (!m) return null;
  const v = parseFloat(m[1]);
  const u = m[2].toLowerCase();
  if (u.startsWith("g")) return v * 1024;
  if (u.startsWith("k")) return v / 1024;
  return v;
}

/* ================= Panel Bot (daftar server ala Pterodactyl) ================= */

export function BotsSection({ refreshKey }) {
  const [data, setData] = useState(null);
  const [view, setView] = useState({ kind: "list" });

  const load = useCallback(async () => {
    const { j } = await api("/api/bots");
    if (j && j.ok) setData(j.data);
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const busy = data && data.bots.some((b) => b.provision && PROVISIONING.includes(b.provision.state));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [busy, load]);

  const bots = data ? data.bots : [];
  const openBot = view.kind === "detail" ? bots.find((b) => b.slug === view.slug) : null;

  if (view.kind === "detail" && openBot) {
    return <BotPage bot={openBot} onReload={load} onBack={() => setView({ kind: "list" })} />;
  }
  if (view.kind === "create" && data) {
    return (
      <section className="blk" style={{ marginTop: 4 }}>
        <CreateBotForm runtimes={data.runtimes}
          onDone={() => { setView({ kind: "list" }); load(); }}
          onCancel={() => setView({ kind: "list" })} />
      </section>
    );
  }

  return (
    <section className="blk" style={{ marginTop: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <h2 style={{ fontSize: 15, margin: 0, display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
          <TerminalIcon />Panel Bot
        </h2>
        <button className="btn sm" onClick={() => setView({ kind: "create" })}>+ Buat Bot</button>
      </div>
      <p className="muted" style={{ margin: "0 0 10px" }}>
        Server bot ala Pterodactyl — tiap bot satu container Docker dengan folder, runtime, dan batas RAM sendiri. Ketuk bot untuk membuka konsolnya.
      </p>
      {!data && <p className="muted">Memuat...</p>}
      {data && !data.docker && <p className="muted">Docker tidak tersedia di perangkat ini.</p>}
      {data && data.docker && bots.length === 0 && (
        <div className="card pad" style={{ textAlign: "center", padding: "22px 14px" }}>
          <p className="muted" style={{ margin: 0 }}>Belum ada server bot. Buat bot pertamamu lewat tombol <b>+ Buat Bot</b> di atas — unggah kode bot WhatsApp / Telegram, pilih runtime, jalankan.</p>
        </div>
      )}
      {bots.map((b) => (
        <BotRow key={b.slug} bot={b} onReload={load} onOpen={() => setView({ kind: "detail", slug: b.slug })} />
      ))}
    </section>
  );
}

function BotRow({ bot, onReload, onOpen }) {
  const { toast, confirm } = useUi();
  const running = bot.state === "running";
  const provisioning = bot.provision && PROVISIONING.includes(bot.provision.state);
  const failed = bot.provision && bot.provision.state === "gagal";
  const usedMB = memToMB(bot.mem_usage);
  const ramPct = usedMB != null && bot.mem_limit_mb ? Math.min(100, Math.round((usedMB / bot.mem_limit_mb) * 100)) : null;

  async function act(action, e) {
    e.stopPropagation();
    const { r, j } = await postJSON("/api/bots/action", { id: bot.slug, action });
    toast(r.ok ? bot.name + ": " + action + " berhasil" : "Gagal: " + ((j && j.error) || r.status));
    setTimeout(onReload, 700);
  }
  function del(e) {
    e.stopPropagation();
    confirm("Hapus bot " + bot.name + "?",
      "Container bot dihapus. File kodenya di " + bot.dir + " tetap disimpan. Hapus permanen beserta file ada di Pengaturan bot.",
      async () => {
        const { r, j } = await postJSON("/api/bots/action", { id: bot.slug, action: "delete" });
        toast(r.ok ? "Bot dihapus (file dipertahankan)" : "Gagal: " + ((j && j.error) || r.status));
        onReload();
      });
  }

  return (
    <div className="card appcard botrow" onClick={onOpen}>
      <div className="row" style={{ border: "none", padding: 0 }}>
        <span className={"dot " + (provisioning ? "unk" : running ? "on" : "off")}></span>
        <div className="grow">
          <div className="nm">{bot.name}</div>
          <div className="meta">
            {provisioning ? "menyiapkan: " + bot.provision.state + "..."
              : failed ? "gagal disiapkan: " + (bot.provision.detail || "").slice(0, 80)
              : bot.installed
                ? (running ? "berjalan" : "berhenti") + (bot.status_text ? " · " + bot.status_text : "")
                : "container belum dibuat"}
          </div>
        </div>
        <span className="chip">{bot.runtime_label}</span>
      </div>
      <div className="resline">
        <span>RAM {usedMB != null ? bot.mem_usage : "–"} / {bot.mem_limit_mb} MB</span>
        <span>CPU {bot.cpu_usage || "–"}</span>
      </div>
      <div className="resbar"><i style={{ width: (ramPct || 0) + "%" }}></i></div>
      <div className="note" style={{ marginTop: 7 }}>{bot.image} · {bot.dir}</div>
      <div className="acts" onClick={(e) => e.stopPropagation()}>
        {!provisioning && bot.installed && !running && <button className="btn sm" onClick={(e) => act("start", e)}>Start</button>}
        {!provisioning && bot.installed && running && <button className="btn sm" onClick={(e) => act("stop", e)}>Stop</button>}
        {!provisioning && bot.installed && running && <button className="btn sm ghost" onClick={(e) => act("restart", e)}>Restart</button>}
        {!provisioning && bot.installed && <button className="btn sm ghost" onClick={onOpen}>Buka Konsol</button>}
        {!provisioning && <button className="btn sm ghost" style={{ color: "#b23a2e" }} onClick={del}>Hapus</button>}
      </div>
    </div>
  );
}

/* ================= buat bot (layar tersendiri) ================= */

function CreateBotForm({ runtimes, onDone, onCancel }) {
  const { toast } = useUi();
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState(runtimes[0] ? runtimes[0].id : "node22");
  const [startCmd, setStartCmd] = useState(runtimes[0] ? runtimes[0].default_start : "");
  const [mem, setMem] = useState(512);
  const [autoRestart, setAutoRestart] = useState(true);
  const [envText, setEnvText] = useState("");
  const [busyNow, setBusyNow] = useState(false);

  function pickRuntime(id) {
    setRuntime(id);
    const rt = runtimes.find((r) => r.id === id);
    if (rt) setStartCmd(rt.default_start);
  }

  async function submit() {
    if (!name.trim()) { toast("Nama bot wajib diisi"); return; }
    setBusyNow(true);
    const { r, j } = await postJSON("/api/bots/create", {
      name: name.trim(), runtime, start_cmd: startCmd, mem_limit_mb: mem,
      auto_restart: autoRestart, env: textToEnv(envText),
    });
    setBusyNow(false);
    if (r.ok) { toast("Bot dibuat — image runtime sedang disiapkan"); onDone(); }
    else toast("Gagal: " + ((j && j.error) || r.status));
  }

  return (
    <div>
      <button className="btn sm ghost" onClick={onCancel} style={{ marginBottom: 10 }}>← Kembali ke Daftar</button>
      <div className="card pad">
        <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>Buat Server Bot</span><b></b></div>
        <label className="muted">Nama bot</label>
        <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="mis. Bot WA Toko" />
        <label className="muted">Runtime</label>
        <select className="select" style={{ width: "100%" }} value={runtime} onChange={(e) => pickRuntime(e.target.value)}>
          {runtimes.map((r) => <option key={r.id} value={r.id}>{r.label} — {r.image}</option>)}
        </select>
        <label className="muted">Perintah start</label>
        <input className="field mono" value={startCmd} onChange={(e) => setStartCmd(e.target.value)} placeholder="node index.js" />
        <label className="muted">Batas RAM</label>
        <select className="select" style={{ width: "100%" }} value={mem} onChange={(e) => setMem(parseInt(e.target.value, 10))}>
          <option value={256}>256 MB</option>
          <option value={512}>512 MB</option>
          <option value={1024}>1024 MB</option>
        </select>
        <label className="muted">Variabel env (satu per baris, KUNCI=nilai — untuk token bot dsb.)</label>
        <textarea className="field mono" rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"BOT_TOKEN=...\nMODE=production"}></textarea>
        <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "10px 0", fontSize: 14 }}>
          <input type="checkbox" checked={autoRestart} onChange={(e) => setAutoRestart(e.target.checked)} />
          Nyala otomatis bila container mati / STB menyala ulang
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" style={{ flex: 1 }} disabled={busyNow} onClick={submit}>Buat Bot</button>
          <button className="btn ghost" style={{ flex: 1 }} onClick={onCancel}>Batal</button>
        </div>
      </div>
    </div>
  );
}

/* ================= halaman bot (sub-tab ala Pterodactyl) ================= */

function BotPage({ bot, onReload, onBack }) {
  const { toast, confirm } = useUi();
  const [sub, setSub] = useState("konsol");
  const running = bot.state === "running";
  const usedMB = memToMB(bot.mem_usage);
  const ramPct = usedMB != null && bot.mem_limit_mb ? Math.min(100, Math.round((usedMB / bot.mem_limit_mb) * 100)) : null;

  async function act(action) {
    const { r, j } = await postJSON("/api/bots/action", { id: bot.slug, action });
    toast(r.ok ? bot.name + ": " + action + " berhasil" : "Gagal: " + ((j && j.error) || r.status));
    setTimeout(onReload, 700);
  }
  function wipe() {
    confirm("Hapus PERMANEN " + bot.name + "?",
      "Container DAN seluruh file kodenya di " + bot.dir + " akan dihapus. Tindakan ini tidak bisa dibatalkan.",
      async () => {
        const { r, j } = await postJSON("/api/bots/action", { id: bot.slug, action: "delete", wipe: true });
        toast(r.ok ? "Bot dan file-nya dihapus" : "Gagal: " + ((j && j.error) || r.status));
        onBack(); onReload();
      });
  }

  return (
    <section className="blk" style={{ marginTop: 4 }}>
      <button className="btn sm ghost" onClick={onBack} style={{ marginBottom: 10 }}>← Semua Bot</button>

      <div className="card pad" style={{ marginBottom: 10 }}>
        <div className="row" style={{ border: "none", padding: 0 }}>
          <span className={"dot " + (running ? "on" : "off")}></span>
          <div className="grow">
            <div className="nm" style={{ fontSize: 16 }}>{bot.name}</div>
            <div className="meta">{bot.runtime_label} · {bot.image} · {bot.dir}</div>
          </div>
          <span className="chip">{running ? "BERJALAN" : "BERHENTI"}</span>
        </div>
        <div className="resline">
          <span>RAM {usedMB != null ? bot.mem_usage : "–"} / {bot.mem_limit_mb} MB</span>
          <span>CPU {bot.cpu_usage || "–"}</span>
          <span>{bot.status_text || ""}</span>
        </div>
        <div className="resbar"><i style={{ width: (ramPct || 0) + "%" }}></i></div>
        <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
          {!running && <button className="btn sm" style={{ flex: 1 }} onClick={() => act("start")}>Start</button>}
          {running && <button className="btn sm" style={{ flex: 1 }} onClick={() => act("stop")}>Stop</button>}
          {running && <button className="btn sm ghost" style={{ flex: 1 }} onClick={() => act("restart")}>Restart</button>}
        </div>
      </div>

      <div className="seg">
        <button className={sub === "konsol" ? "act" : ""} onClick={() => setSub("konsol")}>Konsol</button>
        <button className={sub === "file" ? "act" : ""} onClick={() => setSub("file")}>File</button>
        <button className={sub === "atur" ? "act" : ""} onClick={() => setSub("atur")}>Pengaturan</button>
      </div>

      {sub === "konsol" && <ConsoleBox bot={bot} running={running} />}
      {sub === "file" && <BotFiles bot={bot} />}
      {sub === "atur" && (
        <div>
          <InstallBox bot={bot} />
          <BotSettings bot={bot} onReload={onReload} onWipe={wipe} />
        </div>
      )}
    </section>
  );
}

/* ================= konsol ================= */

function ConsoleBox({ bot, running }) {
  const { toast } = useUi();
  const [logs, setLogs] = useState("Memuat log...");
  const [follow, setFollow] = useState(true);
  const [cmd, setCmd] = useState("");
  const [execOut, setExecOut] = useState("");
  const preRef = useRef(null);

  const load = useCallback(async () => {
    const { j } = await api("/api/bots/logs?id=" + encodeURIComponent(bot.slug) + "&tail=200");
    if (j && j.ok) setLogs(j.data.logs || "(belum ada output — bot belum pernah jalan atau belum menulis log)");
  }, [bot.slug]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!follow) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [follow, load]);
  useEffect(() => {
    if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
  }, [logs]);

  async function runExec() {
    if (!cmd.trim()) return;
    setExecOut("Menjalankan...");
    const { r, j } = await postJSON("/api/bots/exec", { id: bot.slug, cmd: cmd.trim() });
    setExecOut(r.ok ? (j.data.output || "(tanpa output)") : "Gagal: " + ((j && j.error) || r.status));
  }

  return (
    <div className="card pad">
      <div className="kv" style={{ border: "none", paddingTop: 0 }}>
        <span>Konsol Server</span>
        <label style={{ fontSize: 12.5, color: "var(--muted)", display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> ikuti log
        </label>
      </div>
      <pre className="logs" ref={preRef} style={{ maxHeight: 340 }}>{logs}</pre>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input className="field mono" style={{ flex: 1, margin: 0 }} value={cmd} onChange={(e) => setCmd(e.target.value)}
          placeholder={running ? "perintah di dalam container, mis. ls -la" : "bot harus berjalan untuk menjalankan perintah"}
          onKeyDown={(e) => { if (e.key === "Enter") runExec(); }} />
        <button className="btn sm" onClick={runExec}>Jalankan</button>
      </div>
      {execOut && <pre className="logs">{execOut}</pre>}
      <button className="btn sm ghost" style={{ marginTop: 8 }} onClick={() => { load(); toast("Log dimuat ulang"); }}>Muat Ulang Log</button>
    </div>
  );
}

/* ================= berkas bot ================= */

function BotFiles({ bot }) {
  const { toast } = useUi();
  const [rel, setRel] = useState("");
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null);
  const [newName, setNewName] = useState("");
  const abs = bot.dir + (rel ? "/" + rel : "");

  const load = useCallback(async (r) => {
    const target = bot.dir + (r ? "/" + r : "");
    const { j } = await api("/api/files?path=" + encodeURIComponent(target));
    if (j && j.ok) { setItems(j.data.items); setRel(r); }
    else toast("Gagal memuat folder bot");
  }, [bot.dir, toast]);

  useEffect(() => { load(""); }, [load]);

  async function openEditor(pathRel) {
    const { r, j } = await api("/api/bots/file?id=" + encodeURIComponent(bot.slug) + "&path=" + encodeURIComponent(pathRel));
    if (r.ok) setEditing({ path: pathRel, content: j.data.content });
    else toast("Tidak bisa diedit: " + ((j && j.error) || r.status));
  }
  async function saveEditor() {
    const { r, j } = await postJSON("/api/bots/file/save", { id: bot.slug, path: editing.path, content: editing.content });
    if (r.ok) { toast("Tersimpan: " + editing.path); setEditing(null); load(rel); }
    else toast("Gagal simpan: " + ((j && j.error) || r.status));
  }
  async function extract(pathRel) {
    const { r, j } = await postJSON("/api/bots/extract", { id: bot.slug, path: pathRel });
    toast(r.ok ? j.data.message : "Gagal ekstrak: " + ((j && j.error) || r.status));
    if (r.ok) load(rel);
  }
  async function onUpload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("file", f));
    const { r, j } = await api("/api/upload?path=" + encodeURIComponent(abs), { method: "POST", body: fd });
    toast(r.ok ? "Terunggah: " + (j.data.saved || []).join(", ") : "Gagal unggah: " + ((j && j.error) || r.status));
    if (r.ok) load(rel);
  }

  const parent = rel ? rel.replace(/\/[^/]+$/, "") : null;

  if (editing) {
    return (
      <div className="card pad">
        <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>Editor</span><b>{editing.path}</b></div>
        <textarea className="field mono" rows={14} value={editing.content}
          onChange={(e) => setEditing({ ...editing, content: e.target.value })} spellCheck={false}></textarea>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className="btn sm" style={{ flex: 1 }} onClick={saveEditor}>Simpan</button>
          <button className="btn sm ghost" style={{ flex: 1 }} onClick={() => setEditing(null)}>Tutup</button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>Setelah menyimpan perubahan kode, restart botnya agar berlaku (kecuali bot membaca ulang file sendiri).</p>
      </div>
    );
  }

  return (
    <div className="card pad">
      <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>Berkas Bot</span><b>{rel ? "/" + rel : "/"}</b></div>
      <div className="pathbar">
        {parent !== null && <button onClick={() => load(parent)}>← Naik</button>}
        <span style={{ flex: 1 }}></span>
        <label className="btn sm" htmlFor={"up-bot-" + bot.slug} style={{ cursor: "pointer" }}><I.UploadIcon /> Unggah</label>
        <input type="file" id={"up-bot-" + bot.slug} multiple style={{ display: "none" }} onChange={onUpload} />
      </div>
      <div>
        {items === null && <p className="muted">Memuat...</p>}
        {items !== null && items.length === 0 && <p className="muted">Folder masih kosong — unggah kode botmu (boleh file .zip lalu ekstrak).</p>}
        {(items || []).map((it) => {
          const childRel = (rel ? rel + "/" : "") + it.name;
          const childAbs = bot.dir + "/" + childRel;
          return (
            <div className="row" key={it.name}>
              <div className="ficon">{it.dir ? <I.FolderRowIcon /> : <I.FileRowIcon />}</div>
              <div className="grow">
                {it.dir
                  ? <button className="nm" style={{ textAlign: "left", padding: 0 }} onClick={() => load(childRel)}>{it.name}</button>
                  : <a className="nm" style={{ color: "inherit", textDecoration: "none" }} href={"/api/download?path=" + encodeURIComponent(childAbs)}>{it.name}</a>}
                <div className="meta">{it.dir ? "folder" : fmtBytes(it.size)}</div>
              </div>
              {!it.dir && it.name.toLowerCase().endsWith(".zip") && (
                <button className="btn sm ghost" onClick={() => extract(childRel)}>Ekstrak</button>
              )}
              {!it.dir && (
                <button className="btn sm ghost" onClick={() => openEditor(childRel)}>Edit</button>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input className="field" style={{ flex: 1, margin: 0 }} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="nama file baru, mis. index.js" />
        <button className="btn sm ghost" onClick={() => {
          const n = newName.trim();
          if (!n) return;
          setNewName("");
          setEditing({ path: (rel ? rel + "/" : "") + n, content: "" });
        }}>Buat File</button>
      </div>
    </div>
  );
}

/* ================= install + pengaturan ================= */

function InstallBox({ bot }) {
  const { toast } = useUi();
  const [st, setSt] = useState(null);

  const poll = useCallback(async () => {
    const { j } = await api("/api/bots/install-status?id=" + encodeURIComponent(bot.slug));
    if (j && j.ok) setSt(j.data);
  }, [bot.slug]);

  useEffect(() => { poll(); }, [poll]);
  useEffect(() => {
    if (!st || st.state !== "berjalan") return;
    const t = setInterval(poll, 2500);
    return () => clearInterval(t);
  }, [st, poll]);

  async function start() {
    const { r, j } = await postJSON("/api/bots/install-deps", { id: bot.slug });
    toast(r.ok ? "Install paket dimulai..." : "Gagal: " + ((j && j.error) || r.status));
    setTimeout(poll, 500);
  }

  return (
    <div className="card pad" style={{ marginBottom: 10 }}>
      <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>Dependensi</span><b>{st ? st.state : "–"}</b></div>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {bot.runtime.startsWith("node")
          ? "Menjalankan npm install dari package.json di container sementara dengan image yang sama."
          : "Menjalankan pip install -r requirements.txt di container sementara dengan image yang sama."}
      </p>
      <button className="btn sm" disabled={st && st.state === "berjalan"} onClick={start}>
        {st && st.state === "berjalan" ? "Sedang Install..." : "Install Paket"}
      </button>
      {st && st.log && <pre className="logs">{st.log}</pre>}
    </div>
  );
}

function BotSettings({ bot, onReload, onWipe }) {
  const { toast } = useUi();
  const [startCmd, setStartCmd] = useState(bot.start_cmd);
  const [mem, setMem] = useState(bot.mem_limit_mb);
  const [autoRestart, setAutoRestart] = useState(bot.auto_restart);
  const [envText, setEnvText] = useState(envToText(bot.env));

  async function save() {
    const { r, j } = await postJSON("/api/bots/config", {
      id: bot.slug, start_cmd: startCmd, mem_limit_mb: mem,
      auto_restart: autoRestart, env: textToEnv(envText),
    });
    toast(r.ok ? "Pengaturan tersimpan — container dibuat ulang, nyalakan lagi botnya" : "Gagal: " + ((j && j.error) || r.status));
    if (r.ok) setTimeout(onReload, 600);
  }

  return (
    <div className="card pad">
      <div className="kv" style={{ border: "none", paddingTop: 0 }}><span>Pengaturan Server</span><b></b></div>
      <label className="muted">Perintah start</label>
      <input className="field mono" value={startCmd} onChange={(e) => setStartCmd(e.target.value)} />
      <label className="muted">Batas RAM</label>
      <select className="select" style={{ width: "100%" }} value={mem} onChange={(e) => setMem(parseInt(e.target.value, 10))}>
        <option value={256}>256 MB</option>
        <option value={512}>512 MB</option>
        <option value={1024}>1024 MB</option>
      </select>
      <label className="muted">Variabel env (satu per baris, KUNCI=nilai)</label>
      <textarea className="field mono" rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)}></textarea>
      <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "10px 0", fontSize: 14 }}>
        <input type="checkbox" checked={autoRestart} onChange={(e) => setAutoRestart(e.target.checked)} />
        Auto-restart
      </label>
      <button className="btn sm" style={{ width: "100%" }} onClick={save}>Simpan Pengaturan</button>
      <p className="muted">Menyimpan pengaturan membuat ulang container (bot berhenti) supaya konfigurasi baru berlaku.</p>
      <button className="btn sm danger" style={{ width: "100%" }} onClick={onWipe}>Hapus Bot + Seluruh File</button>
    </div>
  );
}
